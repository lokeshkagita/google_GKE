#!/usr/bin/python
#
# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import time
import traceback
from concurrent import futures
import json
import re
from datetime import datetime, timedelta
from collections import defaultdict

import googlecloudprofiler
from google.auth.exceptions import DefaultCredentialsError
import grpc
import google.generativeai as genai

import demo_pb2
import demo_pb2_grpc
from grpc_health.v1 import health_pb2
from grpc_health.v1 import health_pb2_grpc

from opentelemetry import trace
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient, GrpcInstrumentorServer
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from logger import getJSONLogger
logger = getJSONLogger('frauddetectionservice-server')

def initStackdriverProfiling():
    project_id = None
    try:
        project_id = os.environ["GCP_PROJECT_ID"]
    except KeyError:
        pass

    for retry in range(1,4):
        try:
            if project_id:
                googlecloudprofiler.start(service='fraud_detection_server', service_version='1.0.0', verbose=0, project_id=project_id)
            else:
                googlecloudprofiler.start(service='fraud_detection_server', service_version='1.0.0', verbose=0)
            logger.info("Successfully started Stackdriver Profiler.")
            return
        except (BaseException) as exc:
            logger.info("Unable to start Stackdriver Profiler Python agent. " + str(exc))
            if (retry < 4):
                logger.info("Sleeping %d seconds to retry Stackdriver Profiler agent initialization"%(retry*10))
                time.sleep (1)
            else:
                logger.warning("Could not initialize Stackdriver Profiler after retrying, giving up")
    return

class FraudDetectionService(demo_pb2_grpc.FraudDetectionServiceServicer):
    def __init__(self):
        # Initialize Gemini AI if API key is available
        self.gemini_model = None
        gemini_api_key = os.environ.get('GEMINI_API_KEY')
        if gemini_api_key:
            try:
                genai.configure(api_key=gemini_api_key)
                self.gemini_model = genai.GenerativeModel('gemini-pro')
                logger.info("Gemini AI initialized successfully for fraud detection")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini AI: {e}")
        else:
            logger.info("GEMINI_API_KEY not set, using rule-based fraud detection only")

        # In-memory storage for transaction patterns (in production, use Redis/database)
        self.transaction_history = defaultdict(list)
        self.user_patterns = defaultdict(dict)
        
        # Fraud detection thresholds
        self.max_amount_threshold = 10000.0  # $10,000
        self.velocity_threshold = 5  # Max 5 transactions per minute
        self.daily_limit = 50000.0  # $50,000 per day

    def _validate_credit_card(self, credit_card):
        """Basic credit card validation using Luhn algorithm"""
        if not credit_card or not credit_card.credit_card_number:
            return False, "Missing credit card number"
        
        # Remove spaces and non-digits
        card_number = re.sub(r'\D', '', credit_card.credit_card_number)
        
        # Check length
        if len(card_number) < 13 or len(card_number) > 19:
            return False, "Invalid credit card number length"
        
        # Luhn algorithm
        def luhn_check(card_num):
            digits = [int(d) for d in card_num]
            for i in range(len(digits) - 2, -1, -2):
                digits[i] *= 2
                if digits[i] > 9:
                    digits[i] -= 9
            return sum(digits) % 10 == 0
        
        if not luhn_check(card_number):
            return False, "Invalid credit card number"
        
        # Check expiry date
        try:
            exp_month = credit_card.credit_card_expiration_month
            exp_year = credit_card.credit_card_expiration_year
            
            if exp_month < 1 or exp_month > 12:
                return False, "Invalid expiration month"
            
            current_date = datetime.now()
            exp_date = datetime(exp_year, exp_month, 1)
            
            if exp_date < current_date:
                return False, "Credit card expired"
                
        except (ValueError, AttributeError):
            return False, "Invalid expiration date"
        
        return True, "Valid"

    def _check_velocity_fraud(self, user_id, amount):
        """Check for velocity-based fraud patterns"""
        current_time = time.time()
        
        # Clean old transactions (older than 1 minute)
        self.transaction_history[user_id] = [
            (ts, amt) for ts, amt in self.transaction_history[user_id]
            if current_time - ts < 60
        ]
        
        # Check transaction velocity
        recent_transactions = len(self.transaction_history[user_id])
        if recent_transactions >= self.velocity_threshold:
            return True, f"Too many transactions: {recent_transactions} in last minute"
        
        # Check daily spending
        daily_cutoff = current_time - (24 * 3600)
        daily_spending = sum(
            amt for ts, amt in self.transaction_history[user_id]
            if ts > daily_cutoff
        ) + amount
        
        if daily_spending > self.daily_limit:
            return True, f"Daily spending limit exceeded: ${daily_spending:.2f}"
        
        return False, "Velocity check passed"

    def _check_amount_fraud(self, amount):
        """Check for suspicious amounts"""
        if amount <= 0:
            return True, "Invalid amount"
        
        if amount > self.max_amount_threshold:
            return True, f"Amount too high: ${amount:.2f}"
        
        # Check for common fraud amounts
        suspicious_amounts = [9999.99, 5000.00, 1000.00]
        if amount in suspicious_amounts:
            return True, f"Suspicious amount pattern: ${amount:.2f}"
        
        return False, "Amount check passed"

    def _get_ai_fraud_assessment(self, transaction_data):
        """Use AI to assess fraud risk"""
        if not self.gemini_model:
            return 0.0, "AI assessment not available"
        
        try:
            prompt = f"""
            Analyze this payment transaction for fraud risk:
            
            Amount: ${transaction_data.get('amount', 0):.2f}
            Currency: {transaction_data.get('currency', 'USD')}
            Card Type: {transaction_data.get('card_type', 'Unknown')}
            Transaction Time: {transaction_data.get('timestamp', 'Unknown')}
            User Pattern: {transaction_data.get('user_pattern', 'New user')}
            
            Consider these fraud indicators:
            - Unusual amounts or patterns
            - Time-based anomalies
            - Geographic inconsistencies
            - Velocity patterns
            
            Return a fraud risk score from 0.0 (no risk) to 1.0 (high risk) and a brief explanation.
            Format: SCORE:0.X|REASON:explanation
            """
            
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Parse response
            if "|" in response_text:
                parts = response_text.split("|")
                score_part = parts[0].replace("SCORE:", "").strip()
                reason_part = parts[1].replace("REASON:", "").strip() if len(parts) > 1 else "AI assessment"
                
                try:
                    score = float(score_part)
                    return min(max(score, 0.0), 1.0), reason_part
                except ValueError:
                    pass
            
            return 0.2, "AI assessment completed"
                
        except Exception as e:
            logger.warning(f"AI fraud assessment failed: {e}")
            return 0.0, "AI assessment failed"

    def CheckFraud(self, request, context):
        """Main fraud detection endpoint"""
        try:
            # Extract transaction details
            amount = float(request.amount.units + request.amount.nanos / 1e9)
            currency = request.amount.currency_code
            credit_card = request.credit_card
            user_id = getattr(request, 'user_id', 'anonymous')
            
            logger.info(f"[Fraud Check] User: {user_id}, Amount: ${amount:.2f} {currency}")
            
            fraud_reasons = []
            risk_score = 0.0
            
            # 1. Credit card validation
            is_valid, card_message = self._validate_credit_card(credit_card)
            if not is_valid:
                fraud_reasons.append(card_message)
                risk_score += 0.8
            
            # 2. Amount-based checks
            is_amount_fraud, amount_message = self._check_amount_fraud(amount)
            if is_amount_fraud:
                fraud_reasons.append(amount_message)
                risk_score += 0.6
            
            # 3. Velocity checks
            is_velocity_fraud, velocity_message = self._check_velocity_fraud(user_id, amount)
            if is_velocity_fraud:
                fraud_reasons.append(velocity_message)
                risk_score += 0.7
            
            # 4. AI-based assessment
            transaction_data = {
                'amount': amount,
                'currency': currency,
                'card_type': credit_card.credit_card_number[:4] if credit_card.credit_card_number else 'Unknown',
                'timestamp': datetime.now().isoformat(),
                'user_pattern': f"{len(self.transaction_history[user_id])} recent transactions"
            }
            
            ai_score, ai_reason = self._get_ai_fraud_assessment(transaction_data)
            risk_score += ai_score * 0.3  # Weight AI assessment at 30%
            
            # Normalize risk score
            risk_score = min(risk_score, 1.0)
            
            # Determine if transaction should be blocked
            is_fraud = risk_score > 0.7 or len(fraud_reasons) > 0
            
            if not is_fraud:
                # Record successful transaction
                self.transaction_history[user_id].append((time.time(), amount))
            
            # Build response
            response = demo_pb2.FraudCheckResponse()
            response.is_fraud = is_fraud
            response.risk_score = risk_score
            response.reason = "; ".join(fraud_reasons) if fraud_reasons else ai_reason
            
            logger.info(f"[Fraud Result] Fraud: {is_fraud}, Score: {risk_score:.2f}, Reason: {response.reason}")
            
            return response
            
        except Exception as e:
            logger.error(f"Error in fraud detection: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Fraud detection error: {str(e)}")
            
            # Return safe default (block transaction on error)
            response = demo_pb2.FraudCheckResponse()
            response.is_fraud = True
            response.risk_score = 1.0
            response.reason = "System error - transaction blocked for safety"
            return response

    def Check(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.SERVING)

    def Watch(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.UNIMPLEMENTED)


if __name__ == "__main__":
    logger.info("initializing frauddetectionservice")

    try:
        if "DISABLE_PROFILER" in os.environ:
            raise KeyError()
        else:
            logger.info("Profiler enabled.")
            initStackdriverProfiling()
    except KeyError:
        logger.info("Profiler disabled.")

    try:
        grpc_client_instrumentor = GrpcInstrumentorClient()
        grpc_client_instrumentor.instrument()
        grpc_server_instrumentor = GrpcInstrumentorServer()
        grpc_server_instrumentor.instrument()
        if os.environ.get("ENABLE_TRACING") == "1":
            trace.set_tracer_provider(TracerProvider())
            otel_endpoint = os.getenv("COLLECTOR_SERVICE_ADDR", "localhost:4317")
            trace.get_tracer_provider().add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint = otel_endpoint,
                        insecure = True
                    )
                )
            )
    except (KeyError, DefaultCredentialsError):
        logger.info("Tracing disabled.")
    except Exception as e:
        logger.warn(f"Exception on Cloud Trace setup: {traceback.format_exc()}, tracing disabled.") 

    port = os.environ.get('PORT', "8080")

    # create gRPC server
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    # add class to gRPC server
    service = FraudDetectionService()
    demo_pb2_grpc.add_FraudDetectionServiceServicer_to_server(service, server)
    health_pb2_grpc.add_HealthServicer_to_server(service, server)

    # start server
    logger.info("listening on port: " + port)
    server.add_insecure_port('[::]:'+port)
    server.start()

    # keep alive
    try:
        while True:
            time.sleep(10000)
    except KeyboardInterrupt:
        server.stop(0)
