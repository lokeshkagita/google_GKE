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

FROM python:3.11-slim

# Enable unbuffered logging
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /chatbotservice

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the proto files
COPY ./protos/ ./protos/

# Copy the application code
COPY . .

# Generate the gRPC code
RUN python -m grpc_tools.protoc -I=./protos --python_out=. --grpc_python_out=. ./protos/demo.proto
RUN python -m grpc_tools.protoc -I=./protos --python_out=. --grpc_python_out=. ./protos/grpc/health/v1/health.proto

# Create a non-root user
RUN groupadd -r chatbot && useradd -r -g chatbot chatbot
RUN chown -R chatbot:chatbot /chatbotservice
USER chatbot

# Expose the port
EXPOSE 8080

# Run the application
ENTRYPOINT ["python", "chatbot_server.py"]
