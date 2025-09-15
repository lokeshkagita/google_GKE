#!/usr/bin/env python3

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'chatbotservice'))

import chatbot_server
import demo_pb2

class TestChatbotService(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.service = chatbot_server.ChatbotService()
        
    def test_initialization_without_gemini_key(self):
        """Test service initialization without Gemini API key."""
        with patch.dict(os.environ, {}, clear=True):
            service = chatbot_server.ChatbotService()
            self.assertIsNone(service.gemini_model)
    
    @patch('chatbot_server.genai')
    def test_initialization_with_gemini_key(self, mock_genai):
        """Test service initialization with Gemini API key."""
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}):
            mock_model = Mock()
            mock_genai.GenerativeModel.return_value = mock_model
            
            service = chatbot_server.ChatbotService()
            
            mock_genai.configure.assert_called_once_with(api_key='test-key')
            mock_genai.GenerativeModel.assert_called_once_with('gemini-pro')
            self.assertEqual(service.gemini_model, mock_model)
    
    def test_fallback_response_order_query(self):
        """Test fallback response for order-related queries."""
        response = self.service._get_fallback_response("What's my order status?")
        self.assertIn("order", response.lower())
        self.assertIn("track", response.lower())
    
    def test_fallback_response_return_query(self):
        """Test fallback response for return-related queries."""
        response = self.service._get_fallback_response("I want to return this item")
        self.assertIn("return", response.lower())
    
    def test_fallback_response_product_query(self):
        """Test fallback response for product-related queries."""
        response = self.service._get_fallback_response("Do you have this product?")
        self.assertIn("product", response.lower())
    
    def test_fallback_response_shipping_query(self):
        """Test fallback response for shipping-related queries."""
        response = self.service._get_fallback_response("How long does shipping take?")
        self.assertIn("shipping", response.lower())
        self.assertIn("delivery", response.lower())
    
    def test_fallback_response_general_query(self):
        """Test fallback response for general queries."""
        response = self.service._get_fallback_response("Hello")
        self.assertIn("Online Boutique", response)
        self.assertIn("help", response.lower())
    
    @patch('chatbot_server.time.time')
    def test_send_chat_message_success(self, mock_time):
        """Test successful chat message handling."""
        mock_time.return_value = 1234567890
        
        # Mock the AI response method
        self.service._get_ai_response = Mock(return_value="Hello! How can I help you?")
        
        # Create request
        request = demo_pb2.ChatRequest()
        request.message = "Hello"
        request.user_id = "test-user"
        
        # Mock context
        context = Mock()
        
        # Call the method
        response = self.service.SendChatMessage(request, context)
        
        # Verify response
        self.assertEqual(response.message, "Hello! How can I help you?")
        self.assertEqual(response.timestamp, 1234567890)
    
    @patch('chatbot_server.time.time')
    def test_send_support_ticket_success(self, mock_time):
        """Test successful support ticket creation."""
        mock_time.return_value = 1234567890
        
        # Create request
        request = demo_pb2.SupportTicketRequest()
        request.email = "test@example.com"
        request.subject = "Test Issue"
        request.message = "I have a problem"
        request.user_id = "test-user"
        
        # Mock context
        context = Mock()
        
        # Call the method
        response = self.service.SendSupportTicket(request, context)
        
        # Verify response
        self.assertEqual(response.status, "created")
        self.assertIn("TICKET-", response.ticket_id)
        self.assertIn("created", response.message)
    
    @patch('chatbot_server.genai')
    def test_ai_response_with_gemini(self, mock_genai):
        """Test AI response generation with Gemini."""
        # Setup mock
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = "AI generated response"
        mock_model.generate_content.return_value = mock_response
        
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}):
            service = chatbot_server.ChatbotService()
            service.gemini_model = mock_model
            
            response = service._get_ai_response("Hello")
            
            self.assertEqual(response, "AI generated response")
            mock_model.generate_content.assert_called_once()
    
    def test_ai_response_fallback(self):
        """Test AI response falls back to rule-based when Gemini unavailable."""
        # Service without Gemini model
        service = chatbot_server.ChatbotService()
        service.gemini_model = None
        
        response = service._get_ai_response("Hello")
        
        # Should return fallback response
        self.assertIn("Online Boutique", response)

if __name__ == '__main__':
    unittest.main()
