-- 1. Enable the pgvector extension for vector storage and searches
create extension if not exists vector;

-- 2. Create the Bots table (stores configuration for each client bot)
create table if not exists bots (
  id text primary key, -- e.g., 'acme-corp' or a UUID
  name text not null,
  website_url text,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- 3. Create the Documents table (stores text chunks and vector embeddings)
create table if not exists documents (
  id bigint generated always as identity primary key,
  bot_id text references bots(id) on delete cascade not null,
  url text not null,
  content text not null,
  embedding vector(768) not null -- 768 dimensions matches Google's text-embedding-004
);

-- 4. Create the Conversations table (tracks analytics and sessions)
create table if not exists conversations (
  id uuid default gen_random_uuid() primary key,
  bot_id text references bots(id) on delete cascade not null,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- 5. Create the Messages table (stores exact conversation histories)
create table if not exists messages (
  id bigint generated always as identity primary key,
  conversation_id uuid references conversations(id) on delete cascade not null,
  role text not null, -- 'user' or 'assistant'
  content text not null,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- 6. Create index on document embeddings for fast similarity search
create index on documents using hnsw (embedding vector_cosine_ops);

-- 7. Create the RAG matching function
create or replace function match_documents (
  query_embedding vector(768),
  match_threshold float,
  match_count int,
  filter_bot_id text
)
returns table (
  id bigint,
  url text,
  content text,
  similarity float
)
language sql stable
as $$
  select
    documents.id,
    documents.url,
    documents.content,
    1 - (documents.embedding <=> query_embedding) as similarity
  from documents
  where documents.bot_id = filter_bot_id
    and 1 - (documents.embedding <=> query_embedding) > match_threshold
  order by documents.embedding <=> query_embedding
  limit match_count;
$$;
