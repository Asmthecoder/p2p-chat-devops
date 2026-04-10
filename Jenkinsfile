pipeline {
  agent any

  environment {
    IMAGE_NAME = "p2p-chat"
    IMAGE_TAG = "${env.GIT_COMMIT}"
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
        expression { return env.ACR_CREDENTIALS_ID != null && env.ACR_LOGIN_SERVER != null }
      }
      steps {
        withCredentials([usernamePassword(credentialsId: env.ACR_CREDENTIALS_ID, usernameVariable: 'ACR_USER', passwordVariable: 'ACR_PASS')]) {
          sh 'echo ${ACR_PASS} | docker login ${ACR_LOGIN_SERVER} -u ${ACR_USER} --password-stdin'
          sh 'docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}'
          sh 'docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:latest'
          sh 'docker push ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}'
          sh 'docker push ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:latest'
        }
      }
    }

    stage('Deploy to Kubernetes') {
      when {
        expression { return env.KUBE_CONFIG_CREDENTIALS_ID != null && env.ACR_LOGIN_SERVER != null }
      }
      steps {
        withCredentials([file(credentialsId: env.KUBE_CONFIG_CREDENTIALS_ID, variable: 'KUBECONFIG_FILE')]) {
          sh 'mkdir -p $HOME/.kube'
          sh 'cp ${KUBECONFIG_FILE} $HOME/.kube/config'
          sh 'IMAGE_URI=${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}; sed "s|IMAGE_PLACEHOLDER|${IMAGE_URI}|g" k8s/deployment.yaml > /tmp/deployment.yaml'
          sh 'kubectl apply -f k8s/namespace.yaml'
          sh 'kubectl apply -f k8s/configmap.yaml'
          sh 'kubectl apply -f /tmp/deployment.yaml'
          sh 'kubectl apply -f k8s/service.yaml'
          sh 'kubectl apply -f k8s/hpa.yaml'
          sh 'kubectl rollout status deployment/p2p-chat -n p2p-chat --timeout=180s'
          sh 'kubectl get pods -n p2p-chat -o wide'
          sh 'kubectl get svc -n p2p-chat'
        }
      }
    }
  }
}
