# Postgres for records; OpenSearch, SQS and EventBridge Scheduler for search and jobs

Each area's records and the LangGraph checkpoints live in Postgres (a container in dev, Amazon RDS in prod), each area in its own schema. Search over Exemplars and Items runs on OpenSearch, and background jobs run on SQS with EventBridge Scheduler, although Postgres alone could do both with pgvector and a jobs table. The team wanted managed AWS services in prod: OpenSearch's Stempel analyzer handles Polish inflection that Postgres has no dictionary for, and EventBridge Scheduler fires the timed triggers (Lesson end, due time, close time, hand-in polling) without a singleton scheduler inside the worker. We considered DynamoDB and the LangGraph Store for records and rejected both: they lack the joins, transactions and range queries the records and reports need. LangGraph state holds only graph runs and Chat threads, never records.

## Consequences

- The search index is a copy rebuilt from Postgres, never the record itself.
- SQS delivers at least once, so every job handler is idempotent; job status lives in Postgres.
- Dev runs the same code against local stand-ins (an OpenSearch container with Stempel, ElasticMQ, SeaweedFS for S3 since MinIO stopped publishing images). Timed triggers are the one seam with two adapters: EventBridge Scheduler in prod, a local loop posting to the queue in dev.
