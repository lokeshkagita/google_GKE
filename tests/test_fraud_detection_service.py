#!/usr/bin/env python3

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'frauddetectionservice'))

import fraud_detection_server
import demo_pb2

class TestFraudDetectionService(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.service = fraud_detection_server.FraudDetectionService()
        
    def test_initialization_without_gemini_key(self):
        """Test service initialization without Gemini API key."""
        with patch.dict(os.environ, {}, clear=True):
            service = fraud_detection_server.FraudDetectionService()
            self.assertIsNone(service.gemini_model)
    
    def test_valid_credit_card_luhn(self):
        """Test credit card validation with valid Luhn algorithm."""
        # Create valid credit card (test number)
        credit_card = demo_pb2.CreditCardInfo()
        credit_card.credit_card_number = "4532015112830366"  # Valid test number
        credit_card.credit_card_expiration_month = 12
        credit_card.credit_card_expiration_year = 2025
        credit_card.credit_card_cvv = 123
        
        is_valid, message = self.service._validate_credit_card(credit_card)
        self.assertTrue(is_valid)
        self.assertEqual(message, "Valid")
    
    def test_invalid_credit_card_luhn(self):
        """Test credit card validation with invalid Luhn algorithm."""
        credit_card = demo_pb2.CreditCardInfo()
        credit_card.credit_card_number = "1234567890123456"  # Invalid Luhn
        credit_card.credit_card_expiration_month = 12
        credit_card.credit_card_expiration_year = 2025
        
        is_valid, message = self.service._validate_credit_card(credit_card)
        self.assertFalse(is_valid)
        self.assertIn("Invalid credit card number", message)
    
    def test_expired_credit_card(self):
        """Test credit card validation with expired card."""
        credit_card = demo_pb2.CreditCardInfo()
        credit_card.credit_card_number = "4532015112830366"
        credit_card.credit_card_expiration_month = 1
        credit_card.credit_card_expiration_year = 2020  # Expired
        
        is_valid, message = self.service._validate_credit_card(credit_card)
        self.assertFalse(is_valid)
        self.assertIn("expired", message.lower())
    
    def test_amount_fraud_negative_amount(self):
        """Test amount fraud detection with negative amount."""
        is_fraud, message = self.service._check_amount_fraud(-100.0)
        self.assertTrue(is_fraud)
        self.assertIn("Invalid amount", message)
    
    def test_amount_fraud_high_amount(self):
        """Test amount fraud detection with high amount."""
        is_fraud, message = self.service._check_amount_fraud(15000.0)
        self.assertTrue(is_fraud)
        self.assertIn("Amount too high", message)
    
    def test_amount_fraud_suspicious_pattern(self):
        """Test amount fraud detection with suspicious amount pattern."""
        is_fraud, message = self.service._check_amount_fraud(9999.99)
        self.assertTrue(is_fraud)
        self.assertIn("Suspicious amount pattern", message)
    
    def test_amount_fraud_normal_amount(self):
        """Test amount fraud detection with normal amount."""
        is_fraud, message = self.service._check_amount_fraud(99.99)
        self.assertFalse(is_fraud)
        self.assertIn("Amount check passed", message)
    
    @patch('fraud_detection_server.time.time')
    def test_velocity_fraud_too_many_transactions(self, mock_time):
        """Test velocity fraud detection with too many transactions."""
        mock_time.return_value = 1000.0
        
        # Add multiple transactions within the time window
        user_id = "test-user"
        for i in range(6):  # More than threshold of 5
            self.service.transaction_history[user_id].append((999.0, 10.0))
        
        is_fraud, message = self.service._check_velocity_fraud(user_id, 10.0)
        self.assertTrue(is_fraud)
        self.assertIn("Too many transactions", message)
    
    @patch('fraud_detection_server.time.time')
    def test_velocity_fraud_daily_limit_exceeded(self, mock_time):
        """Test velocity fraud detection with daily limit exceeded."""
        mock_time.return_value = 1000.0
        
        # Add transaction that exceeds daily limit
        user_id = "test-user"
        self.service.transaction_history[user_id].append((500.0, 40000.0))  # Large amount
        
        is_fraud, message = self.service._check_velocity_fraud(user_id, 15000.0)  # Would exceed 50k limit
        self.assertTrue(is_fraud)
        self.assertIn("Daily spending limit exceeded", message)
    
    @patch('fraud_detection_server.time.time')
    def test_velocity_fraud_normal_pattern(self, mock_time):
        """Test velocity fraud detection with normal transaction pattern."""
        mock_time.return_value = 1000.0
        
        user_id = "test-user"
        is_fraud, message = self.service._check_velocity_fraud(user_id, 100.0)
        self.assertFalse(is_fraud)
        self.assertIn("Velocity check passed", message)
    
    def test_check_fraud_success_no_fraud(self):
        """Test fraud check with legitimate transaction."""
        # Create valid request
        request = demo_pb2.FraudCheckRequest()
        
        # Valid amount
        request.amount.units = 100
        request.amount.nanos = 0
        request.amount.currency_code = "USD"
        
        # Valid credit card
        request.credit_card.credit_card_number = "4532015112830366"
        request.credit_card.credit_card_expiration_month = 12
        request.credit_card.credit_card_expiration_year = 2025
        request.credit_card.credit_card_cvv = 123
        
        request.user_id = "test-user"
        
        # Mock context
        context = Mock()
        
        # Mock AI assessment to return low risk
        self.service._get_ai_fraud_assessment = Mock(return_value=(0.1, "Low risk"))
        
        response = self.service.CheckFraud(request, context)
        
        self.assertFalse(response.is_fraud)
        self.assertLess(response.risk_score, 0.7)
    
    def test_check_fraud_invalid_card(self):
        """Test fraud check with invalid credit card."""
        request = demo_pb2.FraudCheckRequest()
        
        # Valid amount
        request.amount.units = 100
        request.amount.nanos = 0
        request.amount.currency_code = "USD"
        
        # Invalid credit card
        request.credit_card.credit_card_number = "1234567890123456"  # Invalid Luhn
        request.credit_card.credit_card_expiration_month = 12
        request.credit_card.credit_card_expiration_year = 2025
        
        request.user_id = "test-user"
        
        context = Mock()
        
        response = self.service.CheckFraud(request, context)
        
        self.assertTrue(response.is_fraud)
        self.assertGreater(response.risk_score, 0.7)
        self.assertIn("Invalid credit card number", response.reason)
    
    def test_check_fraud_high_amount(self):
        """Test fraud check with suspiciously high amount."""
        request = demo_pb2.FraudCheckRequest()
        
        # High amount
        request.amount.units = 15000
        request.amount.nanos = 0
        request.amount.currency_code = "USD"
        
        # Valid credit card
        request.credit_card.credit_card_number = "4532015112830366"
        request.credit_card.credit_card_expiration_month = 12
        request.credit_card.credit_card_expiration_year = 2025
        
        request.user_id = "test-user"
        
        context = Mock()
        
        response = self.service.CheckFraud(request, context)
        
        self.assertTrue(response.is_fraud)
        self.assertIn("Amount too high", response.reason)
    
    @patch('fraud_detection_server.genai')
    def test_ai_fraud_assessment_with_gemini(self, mock_genai):
        """Test AI fraud assessment with Gemini."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = "SCORE:0.3|REASON:Moderate risk transaction"
        mock_model.generate_content.return_value = mock_response
        
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}):
            service = fraud_detection_server.FraudDetectionService()
            service.gemini_model = mock_model
            
            transaction_data = {
                'amount': 100.0,
                'currency': 'USD',
                'card_type': '4532',
                'timestamp': '2024-01-01T00:00:00',
                'user_pattern': '0 recent transactions'
            }
            
            score, reason = service._get_ai_fraud_assessment(transaction_data)
            
            self.assertEqual(score, 0.3)
            self.assertEqual(reason, "Moderate risk transaction")
            mock_model.generate_content.assert_called_once()
    
    def test_ai_fraud_assessment_without_gemini(self):
        """Test AI fraud assessment fallback without Gemini."""
        service = fraud_detection_server.FraudDetectionService()
        service.gemini_model = None
        
        transaction_data = {}
        score, reason = service._get_ai_fraud_assessment(transaction_data)
        
        self.assertEqual(score, 0.0)
        self.assertIn("not available", reason)

if __name__ == '__main__':
    unittest.main()
