# TCE — Spécifications d'implémentation V0

Oct 28, 2026 · @KML

## Objectif et périmètre

Ce document donne à un agent de code (Gemini dans Antigravity, par exemple) tout ce qu'il faut pour construire la V0 de la collecte : un collecteur qui remplit une base Postgres, enrichit chaque item et calcule un score de vélocité par topic.

**Livrable de la V0 :** un dépôt Python exécutable en ligne de commande qui, lancé sur une base vide, collecte Hacker News, arXiv et quelques flux RSS, remplit les 6 tables, rattache les items aux topics et écrit un snapshot quotidien par topic.

**Dans le périmètre**

- Collecte de 3 sources : Hacker News, arXiv (cs.AI, cs.CL, cs.LG, cs.CV), flux RSS d'une liste fournie.
- Les 6 tables du document [Modèle logique de données (ERD)](https://claude.ai/artifact/67QW6o4U6qDQTvqahYK9xq).
- Enrichissement par dictionnaire d'alias et par extraction de mots-clés, sans appel LLM.
- Topics déclarés dans un fichier de configuration, rattachement par score de correspondance.
- Snapshots quotidiens et score de vélocité lissé.
- Commandes CLI, tests automatisés, exécution planifiée.

**Hors périmètre (V1 ou plus tard)**

- Hugging Face, Reddit, X.
- NER statistique (spaCy, GLiNER) et étiquetage LLM.
- Embeddings, texte intégral des articles.
- Interface utilisateur, authentification, génération de newsletter.
- Création automatique de topics (ils sont déclarés à la main en V0).

## Stack, contraintes et configuration

Python 3.12, Postgres sur Aiven et un petit nombre de bibliothèques courantes ; aucune dépendance lourde en V0.

| Besoin | Choix | Remarque |
| --- | --- | --- |
| Langage | Python 3.12 | Gestion des dépendances avec `uv` ou `pip` + `pyproject.toml` |
| HTTP | `httpx` | Timeout de 20 s, 3 essais avec attente croissante |
| Base | Postgres (Aiven, plan gratuit) via `psycopg` 3 | 1 Go de disque, 20 connexions, pas de pooling : une seule connexion par processus |
| Flux RSS | `feedparser` |  |
| Mots-clés | `yake` | Extraction non supervisée, FR et EN |
| Entités | `re` de la bibliothèque standard | Une expression régulière compilée à partir des alias, suffisante pour quelques centaines d'alias |
| CLI | `typer` |  |
| Configuration | `pydantic-settings` + fichiers YAML |  |
| Tests et qualité | `pytest`, `ruff` |  |

**Variables d'environnement** (jamais dans le dépôt ; un fichier `.env.example` liste les noms) :

- `DATABASE_URL` : chaîne de connexion Postgres, SSL obligatoire (`sslmode=require`).
- `USER_AGENT` : identifiant du collecteur avec un contact, envoyé à chaque requête.
- `LOG_LEVEL` : `INFO` par défaut.

**Connexion à la base Aiven** (le mot de passe n'est volontairement pas dans ce document) :

| Élément | Valeur |
| --- | --- |
| Hôte | `pg-33ce8135-tce-oreegami.a.aivencloud.com` |
| Port | `26149` |
| Base | `defaultdb` |
| Utilisateur de l'application | `tce_backend` |
| SSL | obligatoire (`sslmode=require`) |

Valeur de `DATABASE_URL`, à renseigner dans le fichier `.env` local et dans les secrets GitHub, jamais dans le dépôt :

```text
postgres://tce_backend:<MOT_DE_PASSE>@pg-33ce8135-tce-oreegami.a.aivencloud.com:26149/defaultdb?sslmode=require
```

L'agent utilise uniquement l'utilisateur `tce_backend`. Le compte administrateur `avnadmin` n'est pas utilisé par l'application.

**Règles transverses**

- Toutes les dates sont en UTC ; `snapshot_date` est la date UTC du jour traité.
- Toute écriture est idempotente : relancer une commande ne crée aucun doublon.
- Une seule connexion Postgres ouverte à la fois, fermée en fin de commande.
- arXiv : une requête toutes les 3 secondes au maximum, une seule connexion, sur l'ensemble du processus.
- Hacker News : 1 requête par seconde au maximum (choix prudent, la limite exacte de l'API n'est pas vérifiée).
- Une source en erreur ne bloque pas les autres : l'erreur est journalisée et la commande continue.
- Aucun secret ni donnée personnelle dans les journaux.

## Structure du dépôt

Un paquet `tce` sous `src/`, une commande par étape du pipeline, des fichiers de configuration séparés du code.

```text
tce/
├── pyproject.toml
├── README.md
├── .env.example
├── config/
│   ├── sources.yaml        # flux RSS et paramètres HN / arXiv
│   ├── topics.yaml         # topics déclarés à la main
│   └── entities.yaml       # dictionnaire d'entités et d'alias
├── sql/
│   └── 001_init.sql        # schéma des 6 tables
├── src/tce/
│   ├── cli.py              # commandes typer
│   ├── settings.py         # lecture des variables d'environnement
│   ├── db.py               # connexion, exécution du SQL, upserts
│   ├── seed.py             # chargement des YAML en base
│   ├── collectors/
│   │   ├── base.py         # type RawItem et fonctions communes
│   │   ├── hackernews.py
│   │   ├── arxiv.py
│   │   └── rss.py
│   ├── enrich/
│   │   ├── entities.py     # reconnaissance par alias
│   │   └── keywords.py     # extraction YAKE
│   ├── topics.py           # rattachement item → topic
│   └── snapshots.py        # composantes et score de vélocité
└── tests/
    ├── fixtures/           # réponses HN, arXiv, RSS enregistrées
    └── test_*.py
```

Les commandes CLI sont détaillées dans la section Orchestration, tests et critères d'acceptation.

## Schéma SQL

Le fichier `sql/001_init.sql` crée les 6 tables du modèle logique ; il doit pouvoir être rejoué sans erreur (`IF NOT EXISTS`).

```sql
CREATE TABLE IF NOT EXISTS entities (
  entity_id      BIGSERIAL PRIMARY KEY,
  canonical_name TEXT NOT NULL,
  type           TEXT NOT NULL CHECK (type IN ('ORG','MODEL','PRODUCT','LIBRARY','PERSON','DATASET','TECHNIQUE')),
  aliases        TEXT[] NOT NULL DEFAULT '{}',
  status         TEXT NOT NULL DEFAULT 'validated' CHECK (status IN ('candidate','validated','rejected')),
  UNIQUE (canonical_name, type)
);

CREATE TABLE IF NOT EXISTS items (
  item_id        BIGSERIAL PRIMARY KEY,
  source         TEXT NOT NULL CHECK (source IN ('hn','arxiv','rss')),
  source_item_id TEXT NOT NULL,
  url            TEXT NOT NULL,
  url_hash       TEXT NOT NULL UNIQUE,
  title          TEXT NOT NULL,
  summary        TEXT,
  lang           TEXT,
  published_at   TIMESTAMPTZ NOT NULL,
  fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  points         INTEGER NOT NULL DEFAULT 0,
  comments       INTEGER NOT NULL DEFAULT 0,
  keywords       TEXT[] NOT NULL DEFAULT '{}',
  entity_ids     BIGINT[] NOT NULL DEFAULT '{}',
  UNIQUE (source, source_item_id)
);
CREATE INDEX IF NOT EXISTS items_published_at_idx ON items (published_at);
CREATE INDEX IF NOT EXISTS items_entity_ids_idx ON items USING GIN (entity_ids);
CREATE INDEX IF NOT EXISTS items_fts_idx ON items
  USING GIN (to_tsvector('simple', title || ' ' || coalesce(summary, '')));

CREATE TABLE IF NOT EXISTS topics (
  topic_id      BIGSERIAL PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  category      TEXT NOT NULL,
  keywords      TEXT[] NOT NULL DEFAULT '{}',
  entity_ids    BIGINT[] NOT NULL DEFAULT '{}',
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS item_topics (
  item_id     BIGINT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
  topic_id    BIGINT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
  match_score REAL NOT NULL,
  PRIMARY KEY (item_id, topic_id)
);
CREATE INDEX IF NOT EXISTS item_topics_topic_idx ON item_topics (topic_id, item_id);

CREATE TABLE IF NOT EXISTS topic_snapshots (
  topic_id         BIGINT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
  snapshot_date    DATE NOT NULL,
  c24              INTEGER NOT NULL,
  baseline7        NUMERIC(10,3) NOT NULL,
  std7             NUMERIC(10,3) NOT NULL,
  distinct_sources INTEGER NOT NULL,
  engagement_sum   INTEGER NOT NULL,
  velocity_score   NUMERIC(10,3) NOT NULL,
  PRIMARY KEY (topic_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS scopes (
  scope_id   BIGSERIAL PRIMARY KEY,
  user_id    TEXT NOT NULL,
  name       TEXT NOT NULL,
  topic_ids  BIGINT[] NOT NULL DEFAULT '{}',
  keywords   TEXT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS scopes_user_idx ON scopes (user_id);
```

**Normalisation des URL et `url_hash` :** mettre le schéma et le domaine en minuscules, retirer le fragment, les paramètres `utm_*` et la barre finale, puis calculer le SHA-256 en hexadécimal. Pour arXiv, l'URL normalisée est `https://arxiv.org/abs/<identifiant sans version>`.

## Collecteurs

Chaque collecteur transforme une source en objets `RawItem`, puis une fonction commune les enrichit et les écrit en base.

**`RawItem`** (dans `collectors/base.py`) : `source`, `source_item_id`, `url`, `title`, `summary`, `lang`, `published_at` (datetime UTC), `points`, `comments`.

**Écriture en base (commune aux trois sources)**

1. Normaliser l'URL et calculer `url_hash`.
2. Enrichir l'item (entités et mots-clés, voir la section suivante).
3. Insérer avec `ON CONFLICT DO NOTHING` : un doublon sur (source, source\_item\_id) ou sur `url_hash` est ignoré.
4. Pour un item déjà présent, mettre à jour seulement `points` et `comments`.
5. Journaliser le nombre d'items vus, nouveaux et mis à jour.

| Source | Cadence | Requête | Champs utilisés |
| --- | --- | --- | --- |
| Hacker News | Toutes les heures | API Algolia `https://hn.algolia.com/api/v1/search_by_date` avec `tags=story`, `numericFilters=created_at_i>{horodatage}`, `hitsPerPage=100`, 5 pages maximum | `objectID`, `title`, `url`, `points`, `num_comments`, `created_at_i`, `story_text` |
| arXiv | Une fois par jour | `https://export.arxiv.org/api/query` avec `search_query=cat:cs.AI OR cat:cs.CL OR cat:cs.LG OR cat:cs.CV`, `sortBy=submittedDate`, `sortOrder=descending`, `max_results=100`, 5 pages maximum | `id`, `title`, `summary`, `published`, lien `abs` |
| Flux RSS | Toutes les heures | Un appel par flux listé dans `config/sources.yaml` | `id` ou `link`, `title`, `summary`, `published_parsed` |

Les noms de champs et les paramètres Algolia ci-dessus viennent de la connaissance générale de ces API et ne sont pas vérifiés dans la documentation officielle : l'agent les confirme par un appel réel avant de les figer dans les fixtures de test.

**Hacker News**

- Fenêtre : les 48 dernières heures à chaque exécution, ce qui met aussi à jour les points et commentaires des posts récents.
- Filtre : ne garder que les posts dont le titre ou le texte contient au moins un alias d'entité ou un mot-clé de topic ; Hacker News est généraliste et le reste n'a pas d'intérêt ici.
- Sans `url` (par exemple un « Ask HN »), utiliser `https://news.ycombinator.com/item?id=<objectID>`.
- `source_item_id` = `objectID` ; `lang` = `en`.

**arXiv**

- `source_item_id` = identifiant arXiv sans numéro de version (par exemple `2501.01234`) ; `url` = `https://arxiv.org/abs/<identifiant>`.
- Normaliser les espaces et retours à la ligne du titre et du résumé.
- S'arrêter de paginer dès qu'un résultat est plus ancien que 48 heures ; au premier lancement, remonter de 7 jours.
- 3 secondes d'attente entre deux requêtes, une seule connexion. `lang` = `en` ; `points` et `comments` = 0.

**Flux RSS**

- `source_item_id` = `id` de l'entrée, sinon son lien.
- Date de publication absente : utiliser l'heure de collecte.
- Résumé : retirer les balises HTML et tronquer à 1 000 caractères.
- `lang` : langue déclarée par le flux, sinon `en`.
- Un flux illisible est journalisé en avertissement et ignoré.
- La liste des flux est fournie par le propriétaire du projet. L'agent crée `config/sources.yaml` avec deux exemples à vérifier (blog Hugging Face, blog OpenAI) que le propriétaire remplace.

## Enrichissement : entités et mots-clés

En V0, l'enrichissement se limite à deux étapes déterministes et gratuites : un dictionnaire d'alias, puis YAKE ; la cascade complète (NER, LLM) viendra en V1.

**Dictionnaire d'entités (`config/entities.yaml`)**

```yaml
- canonical_name: OpenAI
  type: ORG
  aliases: ["OpenAI", "Open AI"]
- canonical_name: GPT-5
  type: MODEL
  aliases: ["GPT-5", "GPT5", "GPT 5"]
```

- `tce seed` charge ce fichier dans `entities` : upsert sur (canonical\_name, type), fusion des alias, statut `validated`.
- L'agent crée un fichier de départ d'au moins 40 entités réparties sur les types ORG, MODEL, PRODUCT, LIBRARY et TECHNIQUE. Ces entités sont une base à relire par le propriétaire du projet.

**Reconnaissance des entités (`enrich/entities.py`)**

1. Charger les entités `validated` et leurs alias au démarrage.
2. Compiler une seule expression régulière avec tous les alias échappés (`re.escape`), triés du plus long au plus court, entourés de bornes de mot : `(?<!\w)(alias1|alias2|…)(?!\w)`.
3. Appliquer sur `title + " " + summary`, insensible à la casse, sauf pour les alias de 3 caractères ou moins, qui sont comparés en respectant la casse.
4. Convertir chaque alias trouvé en `entity_id` ; stocker la liste dédupliquée et triée dans `items.entity_ids`.

**Mots-clés (`enrich/keywords.py`)**

- YAKE sur `title + " " + summary`, langue de l'item, n-grammes de 1 à 2 mots, 8 mots-clés au maximum.
- Retirer tout mot-clé qui recouvre un alias d'entité déjétecté (comparaison insensible à la casse).
- Passer en minuscules, dédupliquer, stocker dans `items.keywords`.

**Commande `tce enrich --since-days N`** : recalcule `keywords` et `entity_ids` des items des N derniers jours, pour appliquer un dictionnaire modifié.

## Topics, rattachement, snapshots et score

Les topics sont déclarés à la main, les items y sont rattachés par un score simple, et chaque jour une ligne par topic résume l'activité et la vélocité.

**Topics (`config/topics.yaml`)**

```yaml
- name: Agents de code
  category: tech
  keywords: ["coding agent", "code generation", "agentic coding"]
  entities: ["Claude Code", "Cursor", "Codex"]
```

`tce seed` charge ce fichier dans `topics`. Chaque nom d'entité doit exister dans `entities` : sinon la commande échoue avec un message qui nomme l'entité manquante. L'agent crée 8 topics d'exemple que le propriétaire relit.

**Rattachement (`tce attach --since-days 7`)**

- Pour chaque item des N derniers jours et chaque topic : `entity_hits` = nombre d'entités du topic présentes dans `items.entity_ids` ; `keyword_hits` = nombre de mots-clés du topic trouvés dans `title + summary` (insensible à la casse).
- `match_score = min(1, 0.5 × entity_hits + 0.25 × keyword_hits)`.
- Si `match_score` ≥ 0,5 (seuil réglable dans `settings.py`), écrire la ligne dans `item_topics` par upsert. Une entité suffit donc, ou deux mots-clés.

**Snapshots (`tce snapshot --date AAAA-MM-JJ`, hier en UTC par défaut)**

Pour chaque topic et le jour D (de 00:00 UTC inclus à 00:00 UTC du lendemain exclu), calculé directement à partir de `item_topics` et `items` selon `published_at` :

| Colonne | Calcul |
| --- | --- |
| `c24` | Nombre d'items rattachés au topic publiés le jour D |
| `baseline7` | Moyenne des 7 comptes quotidiens des jours D−7 à D−1 (un jour sans item compte 0) |
| `std7` | Écart-type de ces 7 comptes (population) |
| `distinct_sources` | Nombre de valeurs distinctes de `items.source` pour le jour D |
| `engagement_sum` | Somme de `points + comments` des items du jour D |
| `velocity_score` | `(c24 + 1) / (baseline7 + 1)` |

- Écriture par upsert sur (topic\_id, snapshot\_date) : relancer la commande remplace la ligne.
- Tant que moins de 7 jours d'items existent avant D, écrire quand même la ligne et journaliser un avertissement : le score n'est pas fiable avant 8 jours de collecte.
- `tce report --date AAAA-MM-JJ` affiche les 10 topics au plus fort `velocity_score`, avec `c24`, `baseline7` et `distinct_sources`.

## Orchestration, tests et critères d'acceptation

La V0 est terminée quand les commandes ci-dessous tournent sur une base vide et que les critères d'acceptation sont tous remplis.

**Commandes CLI**

| Commande | Rôle |
| --- | --- |
| `tce db init` | Exécute `sql/001_init.sql` |
| `tce seed` | Charge `entities.yaml` puis `topics.yaml` en base (upsert) |
| `tce collect --source hn\|arxiv\|rss\|all` | Collecte, enrichit et écrit les items |
| `tce enrich --since-days N` | Recalcule mots-clés et entités des items récents |
| `tce attach --since-days N` | Rattache les items récents aux topics |
| `tce snapshot --date AAAA-MM-JJ` | Écrit les snapshots du jour (hier UTC par défaut) |
| `tce report --date AAAA-MM-JJ` | Affiche les 10 topics au plus fort score |
| `tce run-all` | `collect --source all`, puis `attach --since-days 7`, puis `snapshot` |

Code de sortie : 0 si tout a réussi, 1 si une source ou une étape a échoué (les autres s'exécutent quand même).

**Planification (proposition)**

- Un workflow GitHub Actions horaire lance `tce collect --source hn` puis `tce collect --source rss`.
- Un workflow quotidien à 01:30 UTC lance `tce collect --source arxiv`, `tce attach --since-days 7` puis `tce snapshot`.
- `DATABASE_URL` est fourni par les secrets du dépôt. Tout autre planificateur convient, tant qu'il lance les mêmes commandes.
- Une activité horaire évite aussi l'extinction du service gratuit pour inactivité.

**Tests (`pytest`, aucun appel réseau)**

- `normalize_url` et `url_hash` : retrait de `utm_*`, du fragment, de la barre finale, casse du domaine.
- Parsing arXiv depuis une réponse enregistrée : identifiant sans version, espaces normalisés.
- Parsing Hacker News depuis une réponse enregistrée : repli sur l'URL de discussion quand `url` est absent.
- Parsing RSS : date absente, HTML retiré du résumé, troncature à 1 000 caractères.
- Reconnaissance d'entités : alias, alias le plus long prioritaire, alias courts sensibles à la casse, bornes de mot.
- Mots-clés : aucun mot-clé ne recouvre une entité détectée.
- Rattachement : une entité suffit, un seul mot-clé ne suffit pas, deux mots-clés suffisent.
- Snapshot sur des données synthétiques : scores attendus calculés à la main (par exemple c24 = 6 et baseline7 = 2 donnent 7 / 3 ≈ 2,333).
- Idempotence, avec une base Postgres de test (`TEST_DATABASE_URL`, tests ignorés si absente) : deux exécutions de suite de `collect` sur les mêmes fixtures donnent le même nombre de lignes.

**Critères d'acceptation**

1. `tce db init` puis `tce seed` réussissent sur une base vide et se rejouent sans erreur.
2. `tce collect --source all` remplit `items` avec des lignes des trois sources, sans doublon sur `url_hash`.
3. Relancer `tce collect --source all` immédiatement n'ajoute aucune ligne.
4. Au moins 80 % des items ont une liste `keywords` non vide.
5. Les items qui citent une entité du dictionnaire ont cette entité dans `entity_ids`.
6. `tce attach` puis `tce snapshot` produisent une ligne par topic pour le jour demandé, et `tce report` affiche un classement.
7. `pytest` et `ruff check` passent sans erreur.
8. Aucun secret dans le dépôt ; le README explique l'installation, les variables d'environnement et chaque commande.

## Plan de tâches pour l'agent et questions ouvertes

Dix tâches dans l'ordre ; chacune se termine par des tests qui passent avant de passer à la suivante.

| # | Tâche | Terminée quand |
| --- | --- | --- |
| 1 | Squelette du dépôt, `pyproject.toml`, `settings.py`, CLI vide, `.env.example` | `tce --help` s'affiche, `ruff` passe |
| 2 | `db.py` et `sql/001_init.sql`, commande `db init` | Le schéma se crée deux fois sans erreur |
| 3 | `normalize_url`, `url_hash`, type `RawItem`, écriture commune en base | Tests d'URL et d'idempotence verts |
| 4 | Dictionnaire d'entités, `seed`, `enrich/entities.py` | Tests d'entités verts |
| 5 | `enrich/keywords.py` | Tests de mots-clés verts |
| 6 | Collecteur arXiv | Test de parsing vert, un appel réel limité à 1 page réussi |
| 7 | Collecteur Hacker News (champs confirmés par un appel réel) | Test de parsing vert, un appel réel réussi |
| 8 | Collecteur RSS et `config/sources.yaml` | Test de parsing vert |
| 9 | Topics, `attach`, `snapshot`, `report` | Test de snapshot vert, critères 5 et 6 remplis |
| 10 | `run-all`, workflows de planification, README | Critères 1 à 8 remplis |

**Consignes à l'agent**

- Implémenter uniquement ce que ce document décrit ; toute fonction hors périmètre est notée dans le README comme idée pour la V1.
- En cas d'ambiguïté ou de contradiction avec un appel réel aux API, s'arrêter, l'écrire dans le README (section « Questions ») et choisir l'option la plus simple.
- Ne jamais coder en dur d'identifiants ni d'URL de base de données.
- Respecter les limites d'appel de la section Stack, même dans les tests manuels.

**Questions ouvertes pour le propriétaire**

1. Liste réelle des 15 à 30 flux RSS à suivre.
2. Relecture du dictionnaire de départ d'entités et des 8 topics d'exemple.
3. Seuil de rattachement : 0,5 convient-il après une première semaine de données ?
4. Limites réelles de l'API Hacker News et nom exact des champs : à confirmer par l'agent lors de la tâche 7.
5. Durée de conservation des items pour rester sous 1 Go sur Aiven (voir le document [Modèle logique de données (ERD)](https://claude.ai/artifact/67QW6o4U6qDQTvqahYK9xq)).
