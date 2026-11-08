-- CreateEnum
CREATE TYPE "Provider" AS ENUM ('jira', 'github', 'gitlab', 'msgraph', 'spinach');

-- CreateEnum
CREATE TYPE "ConnectionStatus" AS ENUM ('active', 'needs_reauth', 'revoked');

-- CreateEnum
CREATE TYPE "RunStatus" AS ENUM ('queued', 'running', 'awaiting_review', 'creating_tickets', 'completed', 'failed', 'cancelled');

-- CreateEnum
CREATE TYPE "RunFileKind" AS ENUM ('screenshot', 'transcript');

-- CreateTable
CREATE TABLE "users" (
    "id" UUID NOT NULL,
    "email" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "password_hash" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "refresh_tokens" (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "token_hash" TEXT NOT NULL,
    "family_id" UUID NOT NULL,
    "expires_at" TIMESTAMP(3) NOT NULL,
    "revoked_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "refresh_tokens_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "connections" (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "provider" "Provider" NOT NULL,
    "status" "ConnectionStatus" NOT NULL DEFAULT 'active',
    "external_account_id" TEXT,
    "scopes" TEXT[],
    "access_token_enc" TEXT,
    "refresh_token_enc" TEXT,
    "expires_at" TIMESTAMP(3),
    "meta" JSONB NOT NULL DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,
    "revoked_at" TIMESTAMP(3),

    CONSTRAINT "connections_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "runs" (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "status" "RunStatus" NOT NULL DEFAULT 'queued',
    "input" JSONB NOT NULL,
    "graph_thread_id" TEXT,
    "error" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "runs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "run_events" (
    "id" BIGSERIAL NOT NULL,
    "run_id" UUID NOT NULL,
    "ts" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "step" TEXT NOT NULL,
    "level" TEXT NOT NULL,
    "message" TEXT NOT NULL,
    "data" JSONB NOT NULL DEFAULT '{}',

    CONSTRAINT "run_events_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "run_files" (
    "id" UUID NOT NULL,
    "run_id" UUID NOT NULL,
    "kind" "RunFileKind" NOT NULL,
    "storage_key" TEXT NOT NULL,
    "mime" TEXT NOT NULL,
    "sha256" TEXT NOT NULL,
    "position" INTEGER NOT NULL DEFAULT 0,
    "caption" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "run_files_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "draft_tickets" (
    "id" UUID NOT NULL,
    "run_id" UUID NOT NULL,
    "position" INTEGER NOT NULL,
    "type" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "acceptance_criteria" TEXT[],
    "estimate" TEXT,
    "labels" TEXT[],
    "related_files" TEXT[],
    "selected" BOOLEAN NOT NULL DEFAULT true,
    "edited" BOOLEAN NOT NULL DEFAULT false,
    "jira_key" TEXT,
    "jira_url" TEXT,

    CONSTRAINT "draft_tickets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "audit_log" (
    "id" BIGSERIAL NOT NULL,
    "user_id" UUID,
    "action" TEXT NOT NULL,
    "target" TEXT,
    "ts" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "ip" TEXT,
    "meta" JSONB NOT NULL DEFAULT '{}',

    CONSTRAINT "audit_log_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex
CREATE UNIQUE INDEX "refresh_tokens_token_hash_key" ON "refresh_tokens"("token_hash");

-- CreateIndex
CREATE INDEX "refresh_tokens_user_id_idx" ON "refresh_tokens"("user_id");

-- CreateIndex
CREATE INDEX "refresh_tokens_family_id_idx" ON "refresh_tokens"("family_id");

-- CreateIndex
CREATE UNIQUE INDEX "connections_user_id_provider_key" ON "connections"("user_id", "provider");

-- CreateIndex
CREATE INDEX "runs_user_id_created_at_idx" ON "runs"("user_id", "created_at");

-- CreateIndex
CREATE INDEX "run_events_run_id_id_idx" ON "run_events"("run_id", "id");

-- CreateIndex
CREATE INDEX "run_files_run_id_idx" ON "run_files"("run_id");

-- CreateIndex
CREATE INDEX "draft_tickets_run_id_position_idx" ON "draft_tickets"("run_id", "position");

-- CreateIndex
CREATE INDEX "audit_log_user_id_ts_idx" ON "audit_log"("user_id", "ts");

-- CreateIndex
CREATE INDEX "audit_log_action_ts_idx" ON "audit_log"("action", "ts");

-- AddForeignKey
ALTER TABLE "refresh_tokens" ADD CONSTRAINT "refresh_tokens_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "connections" ADD CONSTRAINT "connections_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "runs" ADD CONSTRAINT "runs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "run_events" ADD CONSTRAINT "run_events_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "run_files" ADD CONSTRAINT "run_files_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "draft_tickets" ADD CONSTRAINT "draft_tickets_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "audit_log" ADD CONSTRAINT "audit_log_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;
