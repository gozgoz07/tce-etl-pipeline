# Trending Content Engine (TCE) — V0

Le moteur **Trending Content Engine (TCE)** collecte automatiquement du contenu technique (Hacker News, arXiv, flux RSS), l'enrichit sans appel LLM (reconnaissance d'entités par dictionnaire d'alias et extraction de mots-clés par YAKE), rattache les items à des topics prédéfinis et calcule quotidiennement un score de vélocité lissé par topic dans une base de données PostgreSQL (Aiven).

---

## 1. Installation

### Prérequis
- Python 3.12+
- Gestionnaire de paquets [`uv`](https://github.com/astral-sh/uv) (ou `pip`)
- Instance PostgreSQL (sur Aiven avec SSL obligatoire `sslmode=require`)

### Cloner et installer les dépendances
```bash
git clone <URL_DU_DEPOT>
cd TCE

# Créer l'environnement virtuel et installer en mode éditable avec dépendances de développement
uv venv
uv pip install -e ".[dev]"

# Ou avec pip standard :
# python -m venv .venv
# source .venv/bin/activate  (ou .venv\Scripts\activate sur Windows)
# pip install -e ".[dev]"
```

---

## 2. Variables d'environnement

Créer un fichier local `.env` à la racine (ignoré par Git). Ne jamais commiter ni publier d'identifiants ou de secrets.

Exemple (voir aussi [`.env.example`](file:///.env.example)) :
```env
# Chaîne de connexion PostgreSQL (SSL obligatoire)
DATABASE_URL=postgres://tce_backend:<MOT_DE_PASSE>@pg-33ce8135-tce-oreegami.a.aivencloud.com:26149/defaultdb?sslmode=require

# Identifiant envoyé dans le header User-Agent HTTP
USER_AGENT=TCE-Collector/0.1.0 (+https://github.com/tce; contact@example.com)

# Niveau de journalisation (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO

# Base de données optionnelle pour les tests d'intégration avec base réelle
# TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/testdb
```

---

## 3. Fichiers de configuration

Trois fichiers YAML sont situés dans le dossier [`config/`](file:///config/) :
- [`config/entities.yaml`](file:///config/entities.yaml) : dictionnaire d'au moins 40 entités réparties sur les types `ORG`, `MODEL`, `PRODUCT`, `LIBRARY` et `TECHNIQUE` avec leurs alias.
- [`config/topics.yaml`](file:///config/topics.yaml) : 8 topics d'exemple avec mots-clés et entités associées.
- [`config/sources.yaml`](file:///config/sources.yaml) : paramètres des sources et deux flux RSS d'exemple (Hugging Face Blog, OpenAI News).

> [!NOTE]
> Ces trois fichiers constituent des bases initiales fournies avec la V0, à relire et adapter par le propriétaire du projet selon les besoins réels de veille.

---

## 4. Commandes CLI (`tce`)

Le paquet fournit le point d'entrée `tce` (Typer) :

| Commande | Rôle |
| :--- | :--- |
| `tce db init` | Crée les 6 tables et index du schéma défini dans [`sql/001_init.sql`](file:///sql/001_init.sql) (idempotent). |
| `tce seed` | Charge `entities.yaml` puis `topics.yaml` en base (upsert avec fusion des alias). |
| `tce collect --source <hn\|arxiv\|rss\|all>` | Collecte les items récents, les normalise, les enrichit et les stocke (idempotent). |
| `tce enrich --since-days <N>` | Recalcule `keywords` et `entity_ids` des items des N derniers jours (7 par défaut). |
| `tce attach --since-days <N>` | Calcule le score de correspondance et rattache les items des N derniers jours aux topics (`match_score >= 0.5`). |
| `tce snapshot --date <AAAA-MM-JJ>` | Calcule les métriques quotidiennes (`c24`, `baseline7`, `std7`, `velocity_score`) par topic (hier UTC par défaut). |
| `tce report --date <AAAA-MM-JJ>` | Affiche le tableau classant les 10 topics au plus fort `velocity_score` (hier UTC par défaut). |
| `tce run-all` | Enchaîne `collect --source all`, puis `attach --since-days 7`, puis `snapshot`. |

**Codes de sortie :**
- `0` : exécution réussie sans erreur.
- `1` : une source ou une étape a échoué (les autres continuent de s'exécuter).

---

## 5. Planification automatique (GitHub Actions)

Deux workflows d'exécution planifiée sont fournis dans [`.github/workflows/`](file:///.github/workflows/) :
1. [`.github/workflows/hourly_collection.yml`](file:///.github/workflows/hourly_collection.yml) : exécution horaire de `tce collect --source hn` puis `tce collect --source rss`.
2. [`.github/workflows/daily_pipeline.yml`](file:///.github/workflows/daily_pipeline.yml) : exécution quotidienne à 01:30 UTC de `tce collect --source arxiv`, `tce attach --since-days 7` puis `tce snapshot`.
3. [`.github/workflows/ci.yml`](file:///.github/workflows/ci.yml) : validation continue sur push/PR avec `pytest` et `ruff check`.

La variable de secret `DATABASE_URL` doit être configurée dans les secrets GitHub du dépôt.

---

## 6. Tests et qualité du code

Lancer la suite de tests et la vérification du code :
```bash
# Vérification du style et linting
uv run ruff check .

# Suite de tests automatisés (sans appel réseau)
uv run pytest
```

---

## 7. Idées V1 (Hors périmètre V0)

- **Sources additionnelles :** collecteurs pour Hugging Face Hub (modèles/datasets tendances), Reddit (r/MachineLearning, r/LocalLLaMA), et X / Twitter.
- **Enrichissement avancé :** NER statistique (spaCy, GLiNER) et étiquetage assisté par LLM.
- **Indexation sémantique :** génération d'embeddings vectoriels et extraction du texte intégral des articles.
- **Interface utilisateur :** dashboard web interactif, authentification utilisateur, et génération automatique de newsletters.
- **Découverte de topics :** clustering non supervisé pour suggérer de nouveaux topics automatiquement.

---

## 8. Questions ouvertes et observations

1. **Connexion et permissions Aiven :** La configuration réseau, le canal SSL obligatoire et les permissions sur le schéma `public` sont pleinement validés. Les 6 tables, les 52 entités initiales et les 8 topics d'exemple sont initialisés et synchronisés.
2. **Durée mesurée de `tce run-all` en production :** L'exécution complète du pipeline en conditions réelles (collecte simultanée de 30 posts Hacker News, 500 prépublications arXiv avec respect du rate limiting de 3 secondes, et 2 223 articles RSS Hugging Face / OpenAI, suivie de l'enrichissement YAKE, de l'attachement aux topics et du calcul des snapshots) a été mesurée à **287,33 secondes** (~4,8 minutes).
3. **Confirmation des champs API Hacker News (Algolia) :** Lors de l'appel réel de la tâche 7, la structure Algolia a confirmé la présence exacte des champs attendus : `objectID`, `title`, `url` (pouvant être `None` pour Ask HN, correctement replié sur `https://news.ycombinator.com/item?id=<objectID>`), `points`, `num_comments`, `created_at_i`, et `story_text`.
4. **Confirmation des champs API arXiv :** L'appel réel de la tâche 6 a validé le flux Atom XML (`atom:id`, `atom:title`, `atom:summary`, `atom:published`), le nettoyage des versions d'identifiant et le respect du délai de 3 secondes par requête.
5. **Flux RSS réels :** Deux flux exemples sont configurés dans `config/sources.yaml` (Hugging Face Blog et OpenAI News). Le propriétaire fournira sa liste de 15 à 30 flux de veille.
6. **Seuil de rattachement topic :** Fixé à `0.5` dans `settings.py` (modifiable via la variable de configuration). Après ingestion réelle de 2 752 items, 141 rattachements item-topic pertinents ont été générés.
7. **Rétention des données :** Sur le plan gratuit Aiven limité à 1 Go, une politique de purge des items de plus de 90 jours pourra être mise en place en V1.
