# Guide de Déploiement et d'Exploitation — TCE (Trending Content Engine)

Ce guide détaille la mise en production du moteur **Trending Content Engine (TCE)**. Il présente l'architecture d'exécution, la configuration pas-à-pas des workflows automatisés (GitHub Actions), la mise en place sur base de données PostgreSQL managée (Aiven), ainsi que l'alternative d'hébergement sur serveur dédié/VPS.

---

## 1. Vue d'ensemble de l'architecture de déploiement

Le TCE a été conçu pour fonctionner en mode **100% Serverless / Sans serveur dédié** dans sa version V0 :
- **Calcul et orchestration planifiée** : Exécutés gratuitement via les runners **GitHub Actions** (`ubuntu-latest`).
- **Base de données persistante** : Hébergée sur **PostgreSQL managé Aiven** (connexion chiffrée SSL obligatoire).
- **Consommation de ressources** : Aucun daemon résident 24/7. Les runners se lancent à la demande, exécutent les tâches Typer en quelques secondes à minutes, puis s'éteignent.

```
┌────────────────────────────────────────────────────────┐
│                   GitHub Actions                       │
│                                                        │
│  ┌───────────────────────┐   ┌──────────────────────┐  │
│  │ hourly_collection.yml │   │  daily_pipeline.yml  │  │
│  │     (Toutes les h)    │   │   (01:30 UTC / j)    │  │
│  │   • HN (Algolia)      │   │   • arXiv (+ HF Daily) │  │
│  │   • Flux RSS          │   │   • Topic Attach     │  │
│  │   • HF Modèles        │   │   • Daily Snapshot   │  │
│  └───────────┬───────────┘   └──────────┬───────────┘  │
│              │                          │
└──────────────┼──────────────────────────┼──────────────┘
               │                          │
               │  DATABASE_URL (SSL)      │
               ▼                          ▼
┌────────────────────────────────────────────────────────┐
│             PostgreSQL Managé (Aiven)                  │
│                                                        │
│   • entities          • items            • scopes      │
│   • topics            • item_topics      • snapshots   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Workflows GitHub Actions déjà configurés

Trois fichiers de workflow prêts pour la production sont situés dans [`.github/workflows/`](file:///.github/workflows/) :

| Fichier | Déclenchement | Rôle & Commandes exécutées |
| :--- | :--- | :--- |
| [`.github/workflows/ci.yml`](file:///.github/workflows/ci.yml) | `push`, `pull_request` sur `main` / `master` | • Validation qualité : `uv run ruff check .`<br>• Tests unitaires : `uv run pytest` |
| [`.github/workflows/hourly_collection.yml`](file:///.github/workflows/hourly_collection.yml) | Cron (`0 * * * *`) + Manuel (`workflow_dispatch`) | • `uv run tce collect --source hn`<br>• `uv run tce collect --source rss`<br>• `uv run tce collect --source hf` |
| [`.github/workflows/daily_pipeline.yml`](file:///.github/workflows/daily_pipeline.yml) | Cron (`30 1 * * *`) + Manuel (`workflow_dispatch`) | • `uv run tce collect --source arxiv` *(avec upvotes/commentaires HF Daily Papers)*<br>• `uv run tce attach --since-days 7`<br>• `uv run tce snapshot` |

> [!TIP]
> Tous les workflows planifiés intègrent l'événement `workflow_dispatch`, ce qui vous permet de déclencher manuellement n'importe quel pipeline à tout moment depuis l'interface web de GitHub (onglet *Actions* > sélectionner le workflow > *Run workflow*).

---

## 3. Guide pas-à-pas : Déploiement Serverless (Recommandé)

### Étape 1 : Initialisation de la base PostgreSQL Aiven

1. **Créer ou récupérer votre instance PostgreSQL sur Aiven Cloud** :
   - Choisir un cluster PostgreSQL (le plan gratuit ou standard convient parfaitement).
   - Récupérer l'URI de connexion complète depuis la console Aiven (dans *Service Overview* > *Connection Details* > *Service URI*).
   - Veiller à ce que le paramètre `sslmode=require` soit bien présent à la fin de l'URI :
     ```text
     postgres://tce_backend:<MOT_DE_PASSE>@<HOST>:<PORT>/defaultdb?sslmode=require
     ```

2. **Exécuter la migration initiale et le seed initial** :
   Depuis votre poste de travail (ou via un terminal de déploiement) avec le fichier `.env` configuré avec la vraie URL Aiven :
   ```bash
   # Création des 6 tables et des index PostgreSQL
   uv run tce db init

   # Chargement initial des entités (config/entities.yaml) et des topics (config/topics.yaml)
   uv run tce seed
   ```

---

### Étape 2 : Configuration du Secret GitHub Repository

Pour que les runners GitHub Actions puissent se connecter à la base de données Aiven :

1. Ouvrez votre dépôt sur **GitHub**.
2. Allez dans **Settings** (Paramètres du dépôt).
3. Dans la colonne de gauche, déroulez **Secrets and variables** puis cliquez sur **Actions**.
4. Cliquez sur le bouton vert **New repository secret**.
5. Renseignez :
   - **Name** : `DATABASE_URL`
   - **Secret** : Collez l'URI de connexion Aiven complète (ex. `postgres://tce_backend:...@...aivencloud.com:.../defaultdb?sslmode=require`).
6. Cliquez sur **Add secret**.

> [!IMPORTANT]
> Ne commitez jamais votre URI de base de données dans le dépôt Git public ou privé. Seul le secret GitHub injecte cette variable de manière sécurisée et masquée dans les logs d'exécution.

---

### Étape 3 : Premier test et validation manuelle

Avant d'attendre la prochaine heure planifiée par les crons, effectuez un test de validation complet via GitHub :

1. Rendez-vous sur l'onglet **Actions** de votre dépôt GitHub.
2. Dans la liste de gauche, cliquez sur **Hourly Collection (HN & RSS)**.
3. Cliquez sur le menu déroulant **Run workflow** à droite, puis sur le bouton vert **Run workflow**.
4. Cliquez sur le job en cours d'exécution pour suivre les logs en direct :
   - Vérification de l'installation `uv` et mise en cache des dépendances.
   - Exécution de `uv run tce collect --source hn`.
   - Exécution de `uv run tce collect --source rss`.
5. Répétez l'opération pour **Daily Pipeline (arXiv, Attach, Snapshot)** pour valider la collecte arXiv et le calcul des snapshots.
6. Le statut doit afficher une coche verte (`Success`).

---

### Étape 4 : Vérification des résultats (Smoke Test)

Depuis votre machine locale connectée à la base de données, vérifiez que les données ont bien été écrites :

```bash
# Afficher le top 10 des topics par vélocité
uv run tce report
```

Ou directement via une requête SQL rapide :
```sql
SELECT source, count(*) FROM items GROUP BY source;
SELECT count(*) FROM item_topics;
SELECT snapshot_date, count(*) FROM topic_snapshots GROUP BY snapshot_date;
```

---

## 4. Alternative : Déploiement sur Serveur Dédié / VPS Linux

Si vous préférez exécuter le moteur sur un serveur Linux (Ubuntu 22.04 / 24.04, Debian) plutôt que sur GitHub Actions :

### 1. Installation des prérequis système
```bash
sudo apt update && sudo apt install -y git curl

# Installer uv (gestionnaire rapide de paquets Python)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### 2. Déploiement de l'application
```bash
# Cloner le dépôt dans /opt/tce
sudo git clone <URL_DU_DEPOT> /opt/tce
sudo chown -R $USER:$USER /opt/tce
cd /opt/tce

# Créer l'environnement virtuel et installer le projet
uv venv
uv sync

# Configurer les variables d'environnement
cp .env.example .env
nano .env   # Renseigner DATABASE_URL avec sslmode=require
chmod 600 .env
```

### 3. Planification via Crontab Linux
Ouvrez le crontab de l'utilisateur :
```bash
crontab -e
```

Ajoutez les entrées suivantes pour répliquer exactement la planification GitHub Actions :
```cron
# Répertoire de logs
# Assurez-vous que /var/log/tce/ existe : sudo mkdir -p /var/log/tce && sudo chown $USER:$USER /var/log/tce

# Collecte horaire (HN + RSS) à la minute 00
0 * * * * cd /opt/tce && uv run tce collect --source hn >> /var/log/tce/hourly.log 2>&1 && uv run tce collect --source rss >> /var/log/tce/hourly.log 2>&1

# Pipeline quotidien (arXiv + Attach 7j + Snapshot) à 01:30 UTC
30 1 * * * cd /opt/tce && uv run tce collect --source arxiv >> /var/log/tce/daily.log 2>&1 && uv run tce attach --since-days 7 >> /var/log/tce/daily.log 2>&1 && uv run tce snapshot >> /var/log/tce/daily.log 2>&1
```

---

## 5. Maintenance, Mises à jour et Exploitation

### Mise à jour des sources et entités
Pour ajouter de nouveaux flux RSS, de nouvelles entités ou de nouveaux topics en production :
1. Éditez localement :
   - [`config/sources.yaml`](file:///config/sources.yaml) : ajout d'URLs de flux RSS.
   - [`config/entities.yaml`](file:///config/entities.yaml) : ajout d'alias ou d'entités techniques.
   - [`config/topics.yaml`](file:///config/topics.yaml) : ajout de règles de topics.
2. Synchronisez en base de données :
   ```bash
   uv run tce seed
   ```
3. Commitez et poussez les modifications sur Git. Les prochains runs GitHub Actions prendront immédiatement en compte les nouvelles règles.

### Gestion du quota de stockage Aiven (Plan 1 Go)
Sur le tier gratuit ou découverte d'Aiven limité à 1 Go :
- Avec ~300 items par jour, la base consomme environ 50 à 100 Mo par an.
- Pour maintenir la base indéfiniment sous le quota de 1 Go, une politique de purge des items de plus de 90 jours peut être exécutée périodiquement :
  ```sql
  DELETE FROM items WHERE published_at < NOW() - INTERVAL '90 days';
  ```
  *(La suppression en cascade nettoiera automatiquement les entrées correspondantes dans `item_topics`)*.

### Alerting et Surveillance
- **Échecs GitHub Actions** : Par défaut, GitHub envoie automatiquement un e-mail au propriétaire du dépôt dès qu'un workflow planifié échoue.
- **Statut de l'instance Aiven** : La console web Aiven fournit des métriques d'utilisation CPU, RAM, IOPS et Espace Disque en temps réel.

---

## 6. Résumé des commandes CLI utiles en exploitation

| Action | Commande |
| :--- | :--- |
| Exécuter tout le pipeline manuellement | `uv run tce run-all` |
| Consulter le classement des tendances | `uv run tce report` (ou `tce report --date AAAA-MM-JJ`) |
| Forcer la ré-indexation des N derniers jours | `uv run tce attach --since-days 14` |
| Re-calculer un snapshot passé | `uv run tce snapshot --date 2026-10-25` |
| Ré-appliquer le dictionnaire d'entités | `uv run tce seed` |
