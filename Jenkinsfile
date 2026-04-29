// ---------------------------------------------------------------------------
// CurrencyFlow CI/CD pipeline.
//
// Jenkins polls GitHub every minute. On a new commit it:
//   1. Checks out the latest code
//   2. Sets up a Python venv and installs dev dependencies
//   3. Runs the pytest suite (with coverage -> coverage.xml)
//   4. Sends analysis + coverage to SonarQube
//   5. Builds a fresh Docker image
//   6. Redeploys the running app container
//
// Required Jenkins credentials (configured in the UI):
//   - sonar-token : Secret Text   = your SonarQube token
//
// Optional (only needed if Push-to-Hub stage is enabled):
//   - dockerhub   : Username/Password = your Docker Hub creds
// ---------------------------------------------------------------------------

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 15, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
        // Prevent two builds from racing on the Deploy stage
        // (which removes + recreates the same container).
        disableConcurrentBuilds()
    }

    environment {
        IMAGE_NAME      = 'currencyflow'
        SONAR_HOST_URL  = 'http://sonarqube:9000'
        DOCKER_NETWORK  = 'currencyflow_currencyflow-net'
        APP_CONTAINER   = 'currencyflow-app'
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
                sh 'git log -1 --pretty=format:"%h %s%n%an, %ar"'
            }
        }

        stage('Install dependencies') {
            steps {
                sh '''
                    python3 -m venv .venv
                    .venv/bin/pip install --quiet --upgrade pip
                    .venv/bin/pip install --quiet -r requirements-dev.txt
                '''
            }
        }

        stage('Run tests') {
            steps {
                sh '.venv/bin/python -m pytest'
            }
            post {
                always {
                    archiveArtifacts artifacts: 'coverage.xml', allowEmptyArchive: true
                }
            }
        }

        stage('SonarQube scan') {
            steps {
                withCredentials([string(credentialsId: 'sonar-token', variable: 'SONAR_TOKEN')]) {
                    sh '''
                        sonar-scanner \
                            -Dsonar.host.url=${SONAR_HOST_URL} \
                            -Dsonar.token=${SONAR_TOKEN}
                    '''
                }
            }
        }

        stage('Build Docker image') {
            steps {
                sh '''
                    docker build \
                        -t ${IMAGE_NAME}:${BUILD_NUMBER} \
                        -t ${IMAGE_NAME}:latest \
                        .
                '''
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    docker rm -f ${APP_CONTAINER} || true
                    docker run -d \
                        --name ${APP_CONTAINER} \
                        --network ${DOCKER_NETWORK} \
                        -p 5000:5000 \
                        --restart unless-stopped \
                        ${IMAGE_NAME}:latest
                '''
            }
        }
    }

    post {
        success {
            echo "Pipeline succeeded. Image tag: ${env.IMAGE_NAME}:${env.BUILD_NUMBER}"
        }
        failure {
            echo 'Pipeline FAILED. Check the stage logs above.'
        }
        always {
            cleanWs()
        }
    }
}
