#!/bin/bash

# Build and push all microservice images to Google Container Registry
# Usage: ./build-and-push-images.sh PROJECT_ID REGION

set -e

PROJECT_ID=${1:-"your-project-id"}
REGION=${2:-"us-central1"}
REGISTRY="${REGION}-docker.pkg.dev"

echo "Building and pushing images for project: ${PROJECT_ID}"
echo "Registry: ${REGISTRY}"

# Configure Docker authentication
gcloud auth configure-docker ${REGISTRY}

# Services to build
SERVICES=(
    "emailservice"
    "checkoutservice" 
    "recommendationservice"
    "frontend"
    "paymentservice"
    "productcatalogservice"
    "cartservice"
    "currencyservice"
    "shippingservice"
    "adservice"
    "loadgenerator"
    "chatbotservice"
    "frauddetectionservice"
)

# Build and push each service
for SERVICE in "${SERVICES[@]}"; do
    echo "Building ${SERVICE}..."
    
    # Copy proto files to service directory
    if [ -d "src/${SERVICE}" ]; then
        cp -r protos src/${SERVICE}/
        
        # Build image
        docker build -t ${REGISTRY}/${PROJECT_ID}/microservices-demo/${SERVICE}:latest src/${SERVICE}/
        
        # Push image
        docker push ${REGISTRY}/${PROJECT_ID}/microservices-demo/${SERVICE}:latest
        
        echo "✓ ${SERVICE} built and pushed successfully"
    else
        echo "⚠ Service directory src/${SERVICE} not found, skipping..."
    fi
done

echo "All images built and pushed successfully!"
echo "Update your Kubernetes manifests to use:"
echo "  Image registry: ${REGISTRY}/${PROJECT_ID}/microservices-demo"
echo "  Image tag: latest"
