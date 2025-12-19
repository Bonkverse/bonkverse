Bonkverse
=========

**Bonkverse** is the resource hub for everything related to the game **Bonk.io** — skins, players, search, stats, tools, and community data.

This repository contains the Django backend that powers Bonkverse.

🧠 Tech Stack
-------------

*   **Python / Django**
    
*   **PostgreSQL** (Dockerized)
    
*   **Redis** (Dockerized)
    
*   **Django ORM + PostgreSQL extensions**
    
*   **Railway** (production)
    
*   **Cloudflare** (production edge / protection)
    

🚀 Local Development Setup
--------------------------

Bonkverse is designed to run **fully locally**, without touching production.

### Prerequisites

Make sure you have:

*   Python **3.10+**
    
*   Docker & Docker Compose
    
*   Homebrew (macOS)
    
*   Git
    

1️⃣ Clone the repository
------------------------

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   git clone https://github.com//bonkverse.git  cd bonkverse   `

2️⃣ Create and activate a virtual environment
---------------------------------------------

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python -m venv .venv  source .venv/bin/activate   `

Install dependencies:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   pip install -r requirements.txt   `

3️⃣ Environment variables
-------------------------

Create a local .env file (this is **not committed**):

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   ENV=local  DEBUG=true  SECRET_KEY=dev-insecure-secret-key  DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5433/bonkverse  REDIS_URL=redis://localhost:6379/0   `

> ⚠️ Do **not** include quotes around values.

A .env.example file is provided for reference.

4️⃣ Start local infrastructure (Postgres + Redis)
-------------------------------------------------

Bonkverse uses Docker for local databases.

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   docker compose up -d   `

This starts:

*   PostgreSQL (on port **5433**)
    
*   Redis (on port **6379**)
    

5️⃣ Run migrations
------------------

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python manage.py migrate   `

6️⃣ Install PostgreSQL extensions (required for search)
-------------------------------------------------------

Bonkverse search relies on PostgreSQL extensions (pg\_trgm, unaccent).

They are installed automatically when seeding, or manually via:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python manage.py init_pg_extensions   `

7️⃣ Populate local development data
-----------------------------------

Bonkverse includes a full local seeding system.

This will:

*   Install Postgres extensions
    
*   Populate fake data for most models
    
*   Populate sample skins for search & UI testing
    

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python manage.py populate_all   `

> This **does not** use production data and is safe to run multiple times.

8️⃣ Create a local admin user
-----------------------------

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python manage.py createsuperuser   `

9️⃣ Run the development server
------------------------------

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python manage.py runserver   `

Open:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   http://localhost:8000   `

Admin panel:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   http://localhost:8000/admin   `

🧪 Working with the Database
----------------------------

### 🟢 Django Shell (Rails console equivalent)

**Recommended daily tool**

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python manage.py shell_plus   `

Examples:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   Skin.objects.count()  Skin.objects.filter(name__icontains="dragon")[:10]  BonkPlayer.objects.all()[:5]   `

### 🟢 Database shell (psql)

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python manage.py dbshell   `

If psql is missing:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   brew install libpq  brew link --force libpq   `

### 🟢 Django Admin

Use Admin for:

*   Browsing data
    
*   Editing records
    
*   Sanity checking relationships
    

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   http://localhost:8000/admin   `

### 🟢 GUI Database Tools (optional)

Recommended:

*   **TablePlus**
    
*   **DBeaver**
    
*   **pgAdmin**
    

Connection info:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   Host: 127.0.0.1  Port: 5433  User: postgres  Password: postgres  Database: bonkverse   `

🔍 Search Notes
---------------

Bonkverse search uses:

*   PostgreSQL full-text search
    
*   pg\_trgm similarity ranking
    

If search errors locally:

*   python manage.py init\_pg\_extensions
    

🔁 Resetting the Local Database
-------------------------------

Equivalent to Rails db:drop db:create db:migrate db:seed:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   python manage.py reset_db  python manage.py migrate  python manage.py populate_all   `

(reset\_db is provided by django-extensions)

🧩 Project Structure (relevant parts)
-------------------------------------

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   bonkverse/  ├── skins/  │   ├── models.py  │   ├── views.py  │   ├── admin.py  │   └── management/  │       └── commands/  │           ├── populate_all.py  │           ├── populate_skins.py  │           ├── init_pg_extensions.py  │           └── ...  ├── docker-compose.yml  ├── manage.py  ├── requirements.txt  └── .env.example   `

🛡 Production vs Local
----------------------

*   **Local** uses Docker + .env
    
*   **Production** runs on Railway
    
*   Never point local code at production databases
    
*   Never commit .env files
    

🤝 Contributing
---------------

1.  Fork the repo
    
2.  Create a feature branch
    
3.  Follow the local setup steps above
    
4.  Make your changes
    
5.  Open a PR
    

If something is unclear or broken locally, please open an issue.

❤️ Acknowledgements
-------------------

Bonkverse is built by the Bonk.io community, for the Bonk.io community.