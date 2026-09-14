#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
    # Load non-comment lines
    export $(grep -v '^#' .env | xargs)
fi

# Variables
IMAGE_NAME="ghcr.io/ai20k-build-phase-cohort-3/p-156:latest"

if [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_PAT" ]; then
    echo "❌ Error: GITHUB_USERNAME and GITHUB_PAT must be set in your .env file."
    echo "Please add them to your .env file:"
    echo "  GITHUB_USERNAME=your_username"
    echo "  GITHUB_PAT=ghp_your_token"
    exit 1
fi

echo "🔑 Logging in to GHCR..."
echo "$GITHUB_PAT" | docker login ghcr.io -u "$GITHUB_USERNAME" --password-stdin

echo "📦 Building Docker image locally..."
docker build -t "$IMAGE_NAME" .

echo "📤 Pushing Docker image to GHCR..."
docker push "$IMAGE_NAME"

if [ -n "$RENDER_DEPLOY_WEBHOOK_URL" ]; then
    echo "🚀 Triggering Render Deploy Webhook..."
    curl -f -X POST "$RENDER_DEPLOY_WEBHOOK_URL"
    echo -e "\n✅ Deployment triggered successfully!"
else
    echo "⚠️ Warning: RENDER_DEPLOY_WEBHOOK_URL is not set in your .env file."
    echo "Skipping webhook trigger. You will need to trigger the deploy manually in Render."
fi
