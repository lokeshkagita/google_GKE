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
import threading

import googlecloudprofiler
from google.auth.exceptions import DefaultCredentialsError
import grpc
import google.generativeai as genai
from flask import Flask, request, jsonify

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
logger = getJSONLogger('chatbotservice-server')

# Create Flask app for HTTP endpoints
app = Flask(__name__)

def initStackdriverProfiling():
    project_id = None
    try:
        project_id = os.environ["GCP_PROJECT_ID"]
    except KeyError:
        pass

    for retry in range(1,4):
        try:
            if project_id:
                googlecloudprofiler.start(service='chatbot_server', service_version='1.0.0', verbose=0, project_id=project_id)
            else:
                googlecloudprofiler.start(service='chatbot_server', service_version='1.0.0', verbose=0)
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

class ChatbotService(demo_pb2_grpc.ChatbotServiceServicer):
    def __init__(self):
        # Initialize Gemini AI if API key is available
        self.gemini_model = None
        gemini_api_key = os.environ.get('GEMINI_API_KEY')
        if gemini_api_key:
            try:
                genai.configure(api_key=gemini_api_key)
                self.gemini_model = genai.GenerativeModel('gemini-2.0-flash')
                logger.info("Gemini AI initialized successfully for chatbot")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini AI: {e}")
        else:
            logger.info("GEMINI_API_KEY not set, using fallback responses")

        # Initialize email service connection
        self.email_service_addr = os.environ.get('EMAIL_SERVICE_ADDR', '')
        if self.email_service_addr:
            self.email_channel = grpc.insecure_channel(self.email_service_addr)
            self.email_stub = demo_pb2_grpc.EmailServiceStub(self.email_channel)
            logger.info(f"Connected to email service at {self.email_service_addr}")

    def _get_ai_response(self, user_message, context=None):
        """Get AI-powered response using Gemini"""
        if not self.gemini_model:
            return self._get_fallback_response(user_message)
        
        try:
            # Create context-aware prompt
            system_prompt = """
            You are a helpful customer support agent for Online Boutique, an e-commerce platform.
            You help customers with:
            - Product inquiries
            - Order status and tracking
            - Returns and refunds
            - Account issues
            - General shopping assistance
            
            Be friendly, professional, and concise. If you cannot help with something,
            politely direct them to contact human support.
            """
            
            full_prompt = f"{system_prompt}\n\nCustomer: {user_message}\n\nAssistant:"
            
            response = self.gemini_model.generate_content(full_prompt)
            return response.text.strip()
                
        except Exception as e:
            logger.warning(f"Gemini AI chat failed: {e}")
            return self._get_fallback_response(user_message)

    def _get_fallback_response(self, user_message):
        """Fallback responses when AI is not available"""
        message_lower = user_message.lower()
        
        if any(word in message_lower for word in ['order', 'tracking', 'status']):
            return "I can help you track your order! Please provide your order number and I'll look it up for you."
        elif any(word in message_lower for word in ['return', 'refund', 'exchange']):
            return "For returns and refunds, please visit our returns page or contact our support team. We're happy to help!"
        elif any(word in message_lower for word in ['product', 'item', 'availability']):
            return "I can help you find products! What are you looking for today?"
        elif any(word in message_lower for word in ['shipping', 'delivery']):
            return "We offer various shipping options. Standard delivery is 3-5 business days, and express is 1-2 days."
        else:
            return "Thank you for contacting Online Boutique support! How can I help you today?"

    def SendChatMessage(self, request, context):
        """Handle chat messages from customers"""
        try:
            user_message = request.message
            user_id = getattr(request, 'user_id', 'anonymous')
            
            logger.info(f"[Chat] User {user_id}: {user_message}")
            
            # Get AI response
            bot_response = self._get_ai_response(user_message)
            
            logger.info(f"[Chat] Bot response: {bot_response}")
            
            # Build response
            response = demo_pb2.ChatResponse()
            response.message = bot_response
            response.timestamp = int(time.time())
            
            return response
            
        except Exception as e:
            logger.error(f"Error in chat service: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Chat service error: {str(e)}")
            return demo_pb2.ChatResponse()

    def SendSupportTicket(self, request, context):
        """Handle support ticket creation and send email notification"""
        try:
            ticket_id = f"TICKET-{int(time.time())}"
            
            # Log the support ticket
            logger.info(f"[Support Ticket] {ticket_id}: {request.subject}")
            
            # Send email notification if email service is available
            if hasattr(self, 'email_stub'):
                try:
                    email_request = demo_pb2.SendOrderConfirmationRequest()
                    email_request.email = request.email
                    email_request.order.order_id = ticket_id
                    
                    self.email_stub.SendOrderConfirmation(email_request)
                    logger.info(f"Support ticket notification sent to {request.email}")
                except Exception as e:
                    logger.warning(f"Failed to send email notification: {e}")
            
            # Build response
            response = demo_pb2.SupportTicketResponse()
            response.ticket_id = ticket_id
            response.status = "created"
            response.message = f"Your support ticket {ticket_id} has been created. We'll get back to you soon!"
            
            return response
            
        except Exception as e:
            logger.error(f"Error creating support ticket: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Support ticket error: {str(e)}")
            return demo_pb2.SupportTicketResponse()

    def Check(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.SERVING)

    def Watch(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.UNIMPLEMENTED)


# Global chatbot service instance for HTTP endpoints
# chatbot_service will be initialized in main()

# HTTP REST endpoints
@app.route('/chat', methods=['POST'])
def http_chat():
    """HTTP endpoint for chat messages"""
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({'error': 'Message is required'}), 400
        
        user_message = data['message']
        user_id = data.get('user_id', 'anonymous')
        
        logger.info(f"[HTTP Chat] User {user_id}: {user_message}")
        
        # Get AI response using the same logic as gRPC
        bot_response = chatbot_service._get_ai_response(user_message)
        
        logger.info(f"[HTTP Chat] Bot response: {bot_response}")
        
        return jsonify({
            'message': bot_response,
            'timestamp': int(time.time())
        })
        
    except Exception as e:
        logger.error(f"Error in HTTP chat: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def http_health():
    """HTTP health check endpoint"""
    return jsonify({'status': 'healthy'})

@app.route('/support-ticket', methods=['POST'])
def http_support_ticket():
    """HTTP endpoint for support tickets"""
    try:
        data = request.get_json()
        if not data or 'subject' not in data:
            return jsonify({'error': 'Subject is required'}), 400
        
        ticket_id = f"TICKET-{int(time.time())}"
        
        logger.info(f"[HTTP Support Ticket] {ticket_id}: {data['subject']}")
        
        # Send email notification if email service is available
        if hasattr(chatbot_service, 'email_stub'):
            try:
                email_request = demo_pb2.SendOrderConfirmationRequest()
                email_request.email = data.get('email', '')
                email_request.order.order_id = ticket_id
                
                chatbot_service.email_stub.SendOrderConfirmation(email_request)
                logger.info(f"Support ticket notification sent to {data.get('email', '')}")
            except Exception as e:
                logger.warning(f"Failed to send email notification: {e}")
        
        return jsonify({
            'ticket_id': ticket_id,
            'status': 'created',
            'message': f'Your support ticket {ticket_id} has been created. We\'ll get back to you soon!'
        })
        
    except Exception as e:
        logger.error(f"Error creating HTTP support ticket: {e}")
        return jsonify({'error': str(e)}), 500

def start_http_server():
    """Start the HTTP server in a separate thread"""
    app.run(host='0.0.0.0', port=8081, debug=False, use_reloader=False)

if __name__ == "__main__":
    logger.info("initializing chatbotservice")
    
    # Declare global variable at the start
    global chatbot_service

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
    service = ChatbotService()
    chatbot_service = service  # Set global instance for HTTP endpoints
    
    demo_pb2_grpc.add_ChatbotServiceServicer_to_server(service, server)
    health_pb2_grpc.add_HealthServicer_to_server(service, server)

    # start gRPC server
    logger.info("listening on port: " + port)
    server.add_insecure_port('[::]:'+port)
    server.start()

    # start HTTP server in a separate thread
    logger.info("starting HTTP server on port 8081")
    http_thread = threading.Thread(target=start_http_server)
    http_thread.daemon = True
    http_thread.start()

    # keep alive
    try:
        while True:
            time.sleep(10000)
    except KeyboardInterrupt:
        server.stop(0)
