-- queries.conversation_id becomes optional (found while validating task 3.7 end to end).
--
-- 0002_conversations made every question belong to a chat. Task 3.6 froze chats behind the `chats` flag (DEV-21):
-- with the flag off a question stands alone and the query flow writes conversation_id null, which the NOT NULL
-- constraint refused, so no question could be recorded. The composite foreign key to conversations (0009) uses
-- MATCH SIMPLE, so a null conversation_id is simply not checked; a non-null one still has to name the author's chat.
alter table queries alter column conversation_id drop not null;
