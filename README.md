# ACEest Fitness & Gym — DevOps Assignment 1

A Flask web version of the ACEest Fitness & Gym application used to demonstrate version control, automated testing, Docker containerization, GitHub Actions CI, and Jenkins builds.

## Application features

- Role-based login screen (demo Admin user)
- Client creation and update
- Program selection and calorie estimation
- Client summary, goals, membership status and expiry
- Weekly adherence/progress logging with chart
- BMI and risk information
- Body metric logging and weight trend chart
- Workout and exercise logging with history
- AI-style workout program generation by experience level
- CSV client export
- PDF client report generation

## Default login

- Username: `admin`
- Password: `admin`

> This is an academic demo credential and should not be used for a real production system.

## Local setup

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5000`

## Run tests manually

```bash
python -m pytest -v
```

## Docker

Build image:

```bash
docker build -t aceest-fitness .
```

Run application:

```bash
docker run --rm -p 5000:5000 aceest-fitness
```

Run tests inside the container:

```bash
docker run --rm aceest-fitness python -m pytest -v
```

## GitHub Actions

`.github/workflows/main.yml` runs for every push and pull request. It:

1. Checks out source code.
2. Sets up Python 3.11.
3. Installs dependencies.
4. Performs Python syntax/build validation.
5. Executes Pytest on the GitHub runner.
6. Builds the Docker image.
7. Executes the Pytest suite inside the Docker image.

## Jenkins

The included `Jenkinsfile` defines a pipeline that:

1. Checks out the Git repository.
2. Builds a clean Docker image.
3. Runs Pytest inside the built image.
4. Cleans up the build image after execution.

For a Jenkins Pipeline job, configure **Pipeline script from SCM**, choose Git, provide the public GitHub repository URL, and use `Jenkinsfile` as the script path.

## Project structure

```text
aceest-fitness-devops/
├── .github/workflows/main.yml
├── static/style.css
├── templates/
│   ├── dashboard.html
│   └── login.html
├── tests/test_app.py
├── app.py
├── Dockerfile
├── Jenkinsfile
├── requirements.txt
├── .dockerignore
├── .gitignore
└── README.md
```

## Health endpoint

`GET /health` returns a small JSON response that can be used as a quick service check.
