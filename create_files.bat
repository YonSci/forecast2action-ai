@echo off

echo Creating project files...

type nul > README.md
type nul > .gitignore
type nul > requirements.txt
type nul > .env.example

type nul > app\__init__.py
type nul > app\api\__init__.py
type nul > app\dashboard\__init__.py
type nul > app\ml\__init__.py
type nul > app\advisory\__init__.py
type nul > app\data_pipeline\__init__.py
type nul > app\utils\__init__.py

type nul > app\dashboard\streamlit_app.py
type nul > app\api\main.py
type nul > app\ml\risk_scoring.py
type nul > app\advisory\advisory_generator.py
type nul > app\data_pipeline\load_sample_data.py
type nul > app\utils\config.py

type nul > configs\config.yaml
type nul > docs\architecture\system_architecture.md
type nul > docs\concept\project_concept.md
type nul > docs\demo\demo_script.md
type nul > frontend\package.json
type nul > frontend\vite.config.js

type nul > frontend\src\App.jsx
type nul > frontend\src\index.jsx
type nul > frontend\src\services\api.js
type nul > frontend\src\pages\Dashboard.jsx
type nul > frontend\src\components\RiskCard.jsx
type nul > frontend\src\components\RiskTable.jsx
type nul > frontend\src\components\AdvisoryPanel.jsx
type nul > frontend\src\components\Header.jsx
type nul > frontend\src\services\api.js
type nul > frontend\src\styles\main.css

echo Files created successfully.
pause