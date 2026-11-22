-- Which embedding model produced each passage's vector (blueprint 11.1 step 9). Vectors from different models are
-- not comparable, so search compares a question only with passages embedded by the same model. Lets indexing move
-- to a fallback model when one model's daily quota is used up. Earlier passages were all embedded with the default.
alter table chunks add column embedding_model text;
update chunks set embedding_model = 'gemini-embedding-001' where embedding is not null and embedding_model is null;
create index chunks_workspace_model on chunks (workspace_id, embedding_model);
