# Image pour un déploiement interne — serveur du groupe, machine de l'équipe
# technique. Pour un usage individuel, `lancer.command` ou `lancer.bat` suffit.
#
#   docker build -t audience-jdg .
#   docker run -p 8501:8501 audience-jdg
#
# Puis ouvrir http://localhost:8501

FROM python:3.12-slim

# Streamlit écrit ses fichiers de travail dans le répertoire personnel.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY jdg/ ./jdg/
COPY .streamlit/ ./.streamlit/

# Les exports d'audience ne sont jamais copiés dans l'image : ils se déposent
# dans l'interface, ou se montent au démarrage avec -v ./data:/app/data
RUN mkdir -p /app/data

# Un utilisateur sans privilèges : rien ici n'a besoin d'être root.
RUN useradd --create-home --home-dir /home/audience audience \
    && chown -R audience:audience /app
USER audience
ENV HOME=/home/audience

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
