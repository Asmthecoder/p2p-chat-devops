pipeline {
  agent any

  environment {
    IMAGE_NAME = "p2p-chat"
    IMAGE_TAG = "${env.GIT_COMMIT}"
    REGISTRY = "ghcr.io"
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Python Lint Check') {
      steps {
        sh 'python -m pip install --upgrade pip'
        sh 'pip install -r requirements.txt'
        sh 'python -m py_compile main.py peer.py ui.py message_store.py encryption.py'
      }
    }

    stage('Build Docker Image') {
      steps {
        sh 'docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .'
      }
    }

    stage('Push Docker Image') {
      when {
        expression { return env.GHCR_CREDENTIALS_ID != null && env.GITHUB_OWNER != null }
      }
      steps {
        withCredentials([usernamePassword(credentialsId: env.GHCR_CREDENTIALS_ID, usernameVariable: 'GHCR_USER', passwordVariable: 'GHCR_TOKEN')]) {
          sh 'echo ${GHCR_TOKEN} | docker login ghcr.io -u ${GHCR_USER} --password-stdin'
          sh 'docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${REGISTRY}/${GITHUB_OWNER}/${IMAGE_NAME}:${IMAGE_TAG}'
          sh 'docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${REGISTRY}/${GITHUB_OWNER}/${IMAGE_NAME}:latest'
          sh 'docker push ${REGISTRY}/${GITHUB_OWNER}/${IMAGE_NAME}:${IMAGE_TAG}'
          sh 'docker push ${REGISTRY}/${GITHUB_OWNER}/${IMAGE_NAME}:latest'
        }
      }
    }

    stage('Deploy to Kubernetes') {
      when {
        expression { return env.KUBE_CONFIG_CREDENTIALS_ID != null && env.GITHUB_OWNER != null }
      }
      steps {
        withCredentials([file(credentialsId: env.KUBE_CONFIG_CREDENTIALS_ID, variable: 'KUBECONFIG_FILE')]) {
          sh 'mkdir -p $HOME/.kube'
          sh 'cp ${KUBECONFIG_FILE} $HOME/.kube/config'
          sh 'IMAGE_URI=${REGISTRY}/${GITHUB_OWNER}/${IMAGE_NAME}:${IMAGE_TAG}; sed "s|IMAGE_PLACEHOLDER|${IMAGE_URI}|g" k8s/deployment.yaml > /tmp/deployment.yaml'
          sh 'kubectl apply -f k8s/namespace.yaml'
          sh 'kubectl apply -f k8s/configmap.yaml'
          sh 'kubectl apply -f /tmp/deployment.yaml'
          sh 'kubectl apply -f k8s/service.yaml'
          sh 'kubectl apply -f k8s/hpa.yaml'
          sh 'kubectl rollout status deployment/p2p-chat -n p2p-chat --timeout=180s'
        }
      }
    }
  }
}
