# Image Comparison

## Setup
* Install Python/Conda
* Create the ENV
  - python -m venv venv_img_comparison
* Activate
  - venv_img_comparison\Scripts\activate
* Install the dependency
  - pip install -r requirements.txt
* Start the Service using flask - Local/Development
  - copy .env.dev .env
  - set FLASK_APP=app.py
  - flask run
* Start the Service using flask - QA
  - copy .env.test .env
  - set FLASK_APP=app.py
  - flask run
* Start the Service using flask - PROD
  - copy .env.prod .env
  - set FLASK_APP=app.py
  - flask run
 
## Use Case
### API#1 - Upload the Image into DB
* ![image](https://github.com/user-attachments/assets/1703231f-cc99-4321-85db-05f8bfdbb93d)

### API#2 - Compare the DB image with the request image along with the imag_id
* ![image](https://github.com/user-attachments/assets/c063fdce-ef57-4193-a9fa-e8ac0930eee3)




