pipeline {
    agent any

    environment {
        IMAGE_NAME = "aceest-fitness:${BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Docker Build') {
            steps {
                sh 'docker build -t $IMAGE_NAME .'
            }
        }

        stage('Pytest in Docker') {
            steps {
                sh 'docker run --rm $IMAGE_NAME python -m pytest -q'
            }
        }
    }

    post {
        always {
            sh 'docker image rm -f $IMAGE_NAME || true'
        }
    }
}
