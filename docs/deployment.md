# GKE Deployment Guide for Online Boutique with AI Services

This guide provides step-by-step instructions to deploy the enhanced Online Boutique application with AI agents to Google Kubernetes Engine (GKE).

## Prerequisites

- Google Cloud Project with billing enabled
- `gcloud` CLI installed and configured
- `kubectl` CLI installed
- Docker installed (for building custom images)
- Gemini API key (optional, for AI features)

## Quick Start

### 1. Set Environment Variables

```bash
export PROJECT_ID=your-project-id
export REGION=us-central1
export CLUSTER_NAME=online-boutique
export GEMINI_API_KEY=your-gemini-api-key  # Optional
```

### 2. Enable Required APIs

```bash
gcloud services enable container.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project=${PROJECT_ID}
```

### 3. Create GKE Cluster

```bash
# Create Autopilot cluster (recommended)
gcloud container clusters create-auto ${CLUSTER_NAME} \
  --project=${PROJECT_ID} \
  --region=${REGION}

# OR create Standard cluster
gcloud container clusters create ${CLUSTER_NAME} \
  --project=${PROJECT_ID} \
  --zone=${REGION}-a \
  --machine-type=e2-standard-2 \
  --num-nodes=3 \
  --enable-autoscaling \
  --min-nodes=1 \
  --max-nodes=10
```

### 4. Get Cluster Credentials

```bash
gcloud container clusters get-credentials ${CLUSTER_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID}
```

## Deployment Options

### Option A: Using Pre-built Images (Fastest)

```bash
# Deploy using existing Kubernetes manifests
kubectl apply -f ./release/kubernetes-manifests.yaml

# Deploy new AI services
kubectl apply -f ./infra/k8s-yamls/gemini-secret.yaml
kubectl apply -f ./infra/k8s-yamls/chatbotservice.yaml
kubectl apply -f ./infra/k8s-yamls/frauddetectionservice.yaml
```

### Option B: Using Helm Charts (Recommended)

```bash
# Install Helm (if not already installed)
curl https://get.helm.sh/helm-v3.12.0-linux-amd64.tar.gz | tar xz
sudo mv linux-amd64/helm /usr/local/bin/

# Update Helm values with your project ID
sed -i "s/PROJECT_ID/${PROJECT_ID}/g" ./infra/helm-charts/online-boutique/values.yaml

# Update Gemini API key (if available)
if [ ! -z "$GEMINI_API_KEY" ]; then
  sed -i "s/PLACEHOLDER_GEMINI_API_KEY/${GEMINI_API_KEY}/g" ./infra/helm-charts/online-boutique/values.yaml
fi

# Deploy using Helm
helm install online-boutique ./infra/helm-charts/online-boutique/
```

### Option C: Build and Deploy Custom Images

```bash
# Set up Artifact Registry
gcloud artifacts repositories create microservices-demo \
  --repository-format=docker \
  --location=${REGION} \
  --project=${PROJECT_ID}

# Configure Docker authentication
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Build and push all images
./scripts/build-and-push-images.sh ${PROJECT_ID} ${REGION}

# Deploy with custom images
helm install online-boutique ./infra/helm-charts/online-boutique/ \
  --set global.projectId=${PROJECT_ID} \
  --set global.imageRegistry=${REGION}-docker.pkg.dev \
  --set gemini.apiKey=${GEMINI_API_KEY}
```

## Verification

### 1. Check Pod Status

```bash
kubectl get pods

# Expected output (all pods should be Running):
# NAME                                     READY   STATUS    RESTARTS   AGE
# adservice-xxx                           1/1     Running   0          2m
# cartservice-xxx                         1/1     Running   0          2m
# chatbotservice-xxx                      1/1     Running   0          2m
# checkoutservice-xxx                     1/1     Running   0          2m
# currencyservice-xxx                     1/1     Running   0          2m
# emailservice-xxx                        1/1     Running   0          2m
# frauddetectionservice-xxx               1/1     Running   0          2m
# frontend-xxx                            1/1     Running   0          2m
# loadgenerator-xxx                       1/1     Running   0          2m
# paymentservice-xxx                      1/1     Running   0          2m
# productcatalogservice-xxx               1/1     Running   0          2m
# recommendationservice-xxx               1/1     Running   0          2m
# redis-cart-xxx                          1/1     Running   0          2m
# shippingservice-xxx                     1/1     Running   0          2m
```

### 2. Get External IP

```bash
kubectl get service frontend-external

# Wait for EXTERNAL-IP to be assigned
# NAME               TYPE           CLUSTER-IP    EXTERNAL-IP     PORT(S)        AGE
# frontend-external  LoadBalancer   10.x.x.x      34.x.x.x        80:30000/TCP   3m
```

### 3. Access the Application

```bash
# Get the external IP
EXTERNAL_IP=$(kubectl get service frontend-external -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Application URL: http://${EXTERNAL_IP}"

# Open in browser
open http://${EXTERNAL_IP}  # macOS
# or visit the URL in your browser
```

## AI Features Configuration

### Setting up Gemini API Key

1. **Get Gemini API Key:**
   - Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
   - Create a new API key
   - Copy the key

2. **Update Secret:**
   ```bash
   # Create or update the secret
   kubectl create secret generic gemini-api-secret \
     --from-literal=api-key=${GEMINI_API_KEY} \
     --dry-run=client -o yaml | kubectl apply -f -
   
   # Restart AI services to pick up the new key
   kubectl rollout restart deployment recommendationservice
   kubectl rollout restart deployment chatbotservice
   kubectl rollout restart deployment frauddetectionservice
   ```

### Testing AI Features

1. **AI-Powered Recommendations:**
   - Add items to cart
   - Check product recommendations on product pages
   - Recommendations should be more contextual with AI enabled

2. **Customer Support Chatbot:**
   - Look for chat widget on the frontend
   - Test various queries about orders, products, returns

3. **Fraud Detection:**
   - Fraud detection runs automatically during checkout
   - Check logs: `kubectl logs -l app=frauddetectionservice`

## Monitoring and Troubleshooting

### View Logs

```bash
# View logs for specific service
kubectl logs -l app=chatbotservice -f

# View logs for all AI services
kubectl logs -l app=recommendationservice -f &
kubectl logs -l app=chatbotservice -f &
kubectl logs -l app=frauddetectionservice -f &
```

### Check Service Health

```bash
# Check service endpoints
kubectl get endpoints

# Test internal connectivity
kubectl run debug --image=busybox -it --rm -- /bin/sh
# Inside the pod:
# nslookup chatbotservice
# nslookup frauddetectionservice
```

### Scale Services

```bash
# Scale AI services based on load
kubectl scale deployment chatbotservice --replicas=3
kubectl scale deployment frauddetectionservice --replicas=2
kubectl scale deployment recommendationservice --replicas=2
```

## Performance Optimization

### Resource Requests and Limits

The AI services are configured with appropriate resource limits:

- **Recommendation Service**: 100m CPU, 220Mi memory (can handle AI processing)
- **Chatbot Service**: 100m CPU, 128Mi memory (lightweight chat responses)
- **Fraud Detection**: 100m CPU, 128Mi memory (fast rule-based + AI analysis)

### Horizontal Pod Autoscaling

```bash
# Enable HPA for AI services
kubectl autoscale deployment chatbotservice --cpu-percent=70 --min=1 --max=5
kubectl autoscale deployment frauddetectionservice --cpu-percent=70 --min=1 --max=3
kubectl autoscale deployment recommendationservice --cpu-percent=70 --min=1 --max=3
```

## Security Considerations

1. **API Key Management:**
   - Store Gemini API key in Kubernetes secrets
   - Use Workload Identity for GCP service authentication
   - Rotate API keys regularly

2. **Network Policies:**
   ```bash
   # Apply network policies to restrict inter-service communication
   kubectl apply -f ./infra/k8s-yamls/network-policies.yaml
   ```

3. **Pod Security:**
   - All services run as non-root users
   - Read-only root filesystems
   - Dropped capabilities

## Cleanup

```bash
# Delete the application
helm uninstall online-boutique
# OR
kubectl delete -f ./release/kubernetes-manifests.yaml
kubectl delete -f ./infra/k8s-yamls/

# Delete the cluster
gcloud container clusters delete ${CLUSTER_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID}
```

## Cost Optimization

1. **Use Autopilot clusters** for automatic resource optimization
2. **Enable cluster autoscaling** to scale nodes based on demand
3. **Use preemptible nodes** for non-production workloads
4. **Set appropriate resource requests/limits** to avoid over-provisioning

## Next Steps

- Set up monitoring with Google Cloud Operations
- Configure CI/CD pipelines for automated deployments
- Implement service mesh with Istio for advanced traffic management
- Add custom metrics and alerting for AI services
- Integrate with Cloud SQL or Firestore for persistent data storage

For more advanced configurations and troubleshooting, refer to the [Google Cloud documentation](https://cloud.google.com/kubernetes-engine/docs).
