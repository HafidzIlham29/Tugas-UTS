pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    // Dipicu otomatis oleh GitHub Webhook (git push ke branch main)
    triggers {
        githubPush()
    }

    environment {
        BACKEND_URL  = 'http://localhost:8000'
        FRONTEND_URL = 'http://localhost:8081'
    }

    stages {

        stage('Checkout') {
            steps {
                // Repo + kredensial PAT dikonfigurasi pada job (Pipeline script from SCM)
                checkout scm
                sh 'git log -1 --oneline'
            }
        }

        stage('Syntax Check') {
            steps {
                sh '''
                    python3 -m py_compile backend/app.py
                    docker compose config -q
                    echo "Syntax Python dan docker-compose.yml valid"
                '''
            }
        }

        stage('Build Image') {
            steps {
                sh 'docker compose build backend'
            }
        }

        stage('Automated Deployment') {
            steps {
                // Tanpa "-v": Named Volume announcement-data TIDAK boleh ikut terhapus
                sh '''
                    docker compose up -d --remove-orphans
                    docker compose exec -T frontend nginx -s reload || true
                    docker compose ps
                '''
            }
        }

        stage('Health Check') {
            steps {
                sh '''
                    ok=0
                    for i in $(seq 1 20); do
                        if curl -fsS "$BACKEND_URL/health" > /dev/null; then
                            ok=1
                            break
                        fi
                        echo "Menunggu backend siap ($i/20)..."
                        sleep 3
                    done

                    if [ "$ok" != "1" ]; then
                        echo "Health check backend GAGAL"
                        docker compose logs --tail 50 backend
                        exit 1
                    fi
                    echo "Backend sehat:"
                    curl -fsS "$BACKEND_URL/health"
                    echo ""

                    # Pastikan Nginx -> backend (via app-net) juga berfungsi
                    curl -fsS "$FRONTEND_URL/api/health" > /dev/null
                    echo "Frontend dan proxy ke backend sehat"
                '''
            }
        }
    }

    post {
        success {
            echo 'Deployment berhasil. Frontend: port 8081, API: port 8000.'
        }
        failure {
            echo 'Pipeline GAGAL. Periksa log stage yang berwarna merah.'
            sh 'docker compose ps || true'
        }
    }
}
