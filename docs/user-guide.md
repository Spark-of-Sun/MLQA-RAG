# Cyte user guide

Cyte, by Onekami, answers questions about your legal and medical documents. Every sentence in an answer cites
the exact passage it came from, and the system checks each sentence against that passage before you see it. If a
sentence cannot be checked, it is removed. If your documents do not answer the question, Cyte says so instead
of guessing.

**Address:** http://localhost:3000 during the preview. Later it will be https://onekami.site.

**Supported browsers:** current Chrome, Edge, Firefox or Safari on a computer. The chat list is hidden on narrow
screens, so use a window at least 1024 pixels wide.

**Getting help:** email help@onekami.site for help using Cyte. For demos, pilots and other questions, email
contact@onekami.site. The website also explains the product (**Product**), how data is protected (**Security**),
plans (**Pricing**) and how to reach us (**Contact**).

> **Preview notice.** In this preview, document text is processed by Google (for search) and by the configured
> answer model. Do not upload real client or patient records until Onekami confirms that the required data
> agreements are in place.

## Contents

1. [How Cyte is organized](#1-how-citebound-is-organized)
2. [Sign up and join](#2-sign-up-and-join)
3. [Super Admin: manage admins](#3-super-admin-manage-admins)
4. [Admin: manage members](#4-admin-manage-members)
5. [Library: upload and share documents](#5-library-upload-and-share-documents)
6. [Ask: questions, answers and chats](#6-ask-questions-answers-and-chats)
7. [Profile](#7-profile)
8. [Audit trail](#8-audit-trail)
9. [Who can see what](#9-who-can-see-what)
10. [Sign-in sessions](#10-sign-in-sessions)
11. [Troubleshooting](#11-troubleshooting)
12. [Not available yet](#12-not-available-yet)
13. [Glossary](#13-glossary)

---

## 1. How Cyte is organized

```
Organization  (your firm or hospital)       run by the Super Admin
├── Workspace A  (for example Litigation)   run by Admin A
│   └── Members A1, A2 …
└── Workspace B  (for example Cardiology)   run by Admin B
    └── Members B1 …
```

- An **organization** is one customer, such as a law firm, hospital or practice. It has one **Super Admin**.
- A **workspace** is a team inside the organization. Each workspace has exactly one **Admin**. Workspaces cannot
  see each other: Admin A never sees Workspace B's documents, members or questions.
- A **Member** belongs to one workspace. Members ask questions and upload their own documents.
- Each person belongs to one organization and holds one role. To change role, the person leaves and joins again.
- People join with a **code** and wait for **approval**. Admins join with the Organization Code and the Super Admin
  approves them. Members join with the admin's invite code and the admin approves them.

### What each role can do

| Task | Super Admin | Admin | Member |
| --- | --- | --- | --- |
| Create the organization | Yes | No | No |
| Generate the Organization Code, approve and suspend admins | Yes | No | No |
| See admins and their usage totals | Yes | No | No |
| Generate the member invite code, approve and suspend members | No | Own workspace | No |
| See members, their profiles and usage counts | No | Own workspace | No |
| Upload documents and ask questions | No | Yes | Yes |
| Share documents | No | With the whole workspace or chosen members | With their admin only |
| Read a member's private documents | No | No | Only their own |
| Read someone else's chats | No | No | No |
| Audit trail | Organization and admin events | Whole workspace | Own activity |
| Verify the audit hash chain | Yes | Yes | Yes |

The Super Admin governs the organization but never reads workspace documents, members' details or questions.
This is enforced by the database, not only hidden in the menus.

---

## 2. Sign up and join

1. Open the address above and select **Get started** (new account) or **Sign in** (existing account) at the top
   right of the website.
2. Sign in on the login page with your email and password, or another method your organization has turned on.
   Verify your email if asked.
3. The first time, Cyte asks **"Welcome. How will you use it?"** and shows three cards. Pick the one that
   fits you. You can belong to one organization only.

### 2.1 Create an organization (you become the Super Admin)

1. Select **Create an organization**.
2. Enter the **Organization name** (for example "Hale & Partners LLP").
3. Choose the **Type**: legal, medical or both. This sets the example questions shown in Ask.
4. Select **Create organization**. You land on **Manage admins**. Continue with [section 3](#3-super-admin-manage-admins).

### 2.2 Join as an admin

You need the 64-character Organization Code, or an invite link, from your Super Admin.

1. If you have an **invite link**, open it and sign in. The code is filled in for you.
   Otherwise select **Join as an admin** and paste the code. Dashes and spaces are ignored, and lower case is fine.
2. Enter **Name your workspace** (for example "Litigation" or "Cardiology").
3. Select **Send request**.
4. You see **Waiting for approval** until the Super Admin approves you. Select **Check again** to refresh, or
   **Withdraw request** to cancel.

### 2.3 Join a workspace as a member

You need the 32-character invite code, or an invite link, from your workspace admin.

1. Open the invite link and sign in, or select **Join a workspace** and paste the code.
2. Select **Continue**. Cyte shows the workspace, organization and admin you are joining. Check them.
3. Select **Request to join**, or **Use another code** if the details are wrong.
4. You see **Waiting for approval** until the admin approves you.

The form checks the code as you type and warns you about a typo before you send it. A wrong, used-up or expired
code always gives the same message: **"Code invalid or expired."** Ask the person who sent it for a new one.

---

## 3. Super Admin: manage admins

**Manage admins** is your home page.

### Invite admins

1. In the **Organization Code** panel, select **Generate code** (or **Rotate code** if one exists).
2. The code is shown **once**. Select **Copy code** or **Copy invite link** and send it to the people who will run
   workspaces. Use a private channel. Then select **Done**.
3. The code works for **30 days** and up to **25 requests**. The panel then shows only the lookup ID, the expiry date
   and the number of uses, never the code itself.
4. Rotating the code stops the old one at once. Use it if a code may have leaked. A leaked code can only create a
   request that you can reject.

### Approve and manage admins

The **Admins and workspaces** table lists every admin. Requests awaiting approval are highlighted.

| Column | Meaning |
| --- | --- |
| Admin | Name and email |
| Workspace | The name the admin gave their workspace |
| Status | pending, active, suspended or rejected |
| Members | Active members, plus pending requests shown as "+n" |
| Documents | Number of documents in the workspace (a count only) |
| Questions (30 d) | Questions asked in the workspace over the last 30 days |
| Last active | When the admin last used Cyte |

Actions: **Approve** or **Reject** a request; **Suspend** an active admin; **Reactivate** a suspended one. Reject and
Suspend ask you to confirm.

Suspending an admin **freezes the whole workspace**: the admin and all its members lose access on their next click.
No data is deleted. Reactivating restores the admin and the members who were cut off by the suspension.

---

## 4. Admin: manage members

After approval, sign in again. As an admin you see **Ask**, **Library**, **Manage members**, **Audit trail** and
**Profile**.

### Invite members

In the **Member invite code** panel, select **Generate code**. The code is shown once. Copy the code or the invite
link and send it to your members. It works for **90 days** and up to **100 requests**. **Rotate code** stops the old
code at once.

### Approve and manage members

The **Members** table lists everyone in your workspace, with pending requests highlighted.

| Column | Meaning |
| --- | --- |
| Member | Name, job title and email. Click the name for their profile and usage. |
| Status | pending, active, suspended or rejected |
| Private documents | Documents only that member can see. You see the count, never the documents. |
| Shared with you | Documents the member shared with you. They appear in your Library. |
| Shared by you | Documents you gave this member: shared with them by name, plus everything you shared with the whole workspace. The small line shows the split. |
| Questions | Every question the member asked. Each question in a chat counts, not the number of chats. |
| Tokens | Approximate model usage for their questions (answering, understanding follow-ups and checking answers). Search is not included. |
| Last active | When the member last used Cyte |

Actions: **Approve**, **Reject**, **Suspend** and **Reactivate**. A suspended member sees **Access is paused** and
cannot open anything until you reactivate them.

Clicking a member opens their **profile** (email, job title, department, phone, dates) and **usage** (documents
uploaded, private, shared with you, shared by you, questions, tokens, last question). You see counts only. Their
questions, answers, chats and private documents stay private.

---

## 5. Library: upload and share documents

Admins and members use **Library** to add documents and see what they can search.

### Upload

1. Drag files onto the upload area, or select **Choose files**. You can add several at once.
2. Choose who can use them (see below) **before** you upload. Sharing cannot be changed after upload in this
   version; to change it, delete the document and upload it again.
3. Each file shows **processing** while Cyte reads it, then **ready** with the number of passages and pages.
   You can ask questions about a document once it is ready.

**Accepted files**, up to 25 MB each:

- PDF with selectable text. Scanned PDFs (pictures of pages) are not supported yet.
- Word (DOCX)
- Web pages (HTML)
- XML: journal articles (JATS), drug labels (SPL) and US regulations (eCFR)
- Plain text (TXT, MD)

Cyte splits documents along their headings, sections and clauses so citations point to the right place. If a
file has no headings, the Library notes "No headings detected: split into paragraphs." Answers still work, but
citations show less section detail. A yellow note means some pages had no text (usually scanned pages) and were
skipped.

### Sharing choices

**If you are an admin**, choose under **Who can use these documents?**

- **Whole workspace**: every member of your workspace can search it, including members who join later.
- **Selected members**: tick the members who may search it. Use **Select all** or **Clear** for speed. Only active
  members are listed.
- **Only me**: private to you.

**If you are a member**, your uploads are private by default. Tick **Share with my workspace admin** to let your
admin see the document in their Library and ask questions about it. Members cannot share with other members.

### The Access column

| Badge | Meaning |
| --- | --- |
| Private | Only you can see it |
| Shared by you, with the whole workspace | You (an admin) shared it with everyone in the workspace |
| Shared by you, with *names* | You shared it with the people listed. Hover to see all names. |
| Shared by you, with your admin (*name*) | You (a member) shared it with your admin |
| Shared by admin, with you / with the whole workspace | Your admin shared it with you or with everyone |
| Shared by member, *name*, with you | A member shared it with you (admins only) |

### Delete

Select **Delete** and confirm. You can delete your own documents. Admins can also delete documents shared with the
whole workspace. A deleted document disappears from search at once. Past answers that cited it remain in your chats,
but their source panel says the source is no longer available.

---

## 6. Ask: questions, answers and chats

### Ask a question

1. Select **Ask**. The page shows example questions; click one to try it, or type your own.
2. Type your question and press **Enter** (Shift+Enter adds a new line). Questions can be up to 2,000 characters.
3. Cyte searches the documents you can access, drafts an answer and checks every sentence. This usually
   takes 5 to 20 seconds. Nothing appears until the checks are done.

Answers use only the documents **you** can access: your own, plus those shared with you or with your workspace.

### Read the answer

- **Numbers after sentences** (for example **1**) are citations. Click one to open the **source panel** on the right.
  It shows the document, section and page, with the exact passage highlighted. The highlighted text is what the
  sentence was checked against.
- **Source cards** below the answer list every cited document with its section and pages.
- **"The provided documents do not address this."** means your documents do not support an answer, so none was
  given. If the documents answer only part of the question, you get that part followed by this sentence.
- **"A claim in this answer could not be verified and was removed"** marks a sentence that failed a check. The reason
  is shown in brackets. The rest of the answer is still verified.
- **Verification details** (the line with the shield, for example "4 sentences verified · 1 removed") opens the list
  of checks run on each sentence:

  | Check | What it confirms |
  | --- | --- |
  | Citation format | The citation points to a real source of this answer |
  | Source was retrieved for this question | The answer cites only passages found for this question |
  | Source unchanged since retrieval | The passage did not change between search and answer |
  | Sentence is cited | The sentence has a citation |
  | Quoted text found in source | The supporting quote appears word for word in the passage |
  | Numbers and dates match the source | Every number, date, amount and dosage appears in the passage |
  | Wording supported by the source | The sentence's key terms come from the passage |
  | Source entails the claim | A second, stricter review confirms the passage supports the claim |
  | Refusal wording | A "does not address" sentence is exact and stands alone |
  | Citation resolves to a page and section | The citation leads to a real location in the document |

  The details also name the model that wrote the draft.

Cyte reports what your documents say. It does not give legal or medical advice.

### Follow-up questions

Ask follow-ups in the same chat, as you would with a colleague: "and what must the Executive sign first?" Cyte
uses the conversation to understand the follow-up, and shows how it read it under your question
("Searched as: …"). The answer is still checked against your documents, not against the earlier answers.

### Chats

- The list on the left groups your chats by Today, Yesterday, Previous 7 days and Older.
- **New chat** starts a fresh conversation. A new chat is named after its first question.
- Hover over a chat to **rename** it (pencil) or **delete** it (bin, then **Delete** to confirm).
- On the Ask page, **Continue where you left off** opens your most recent chat.
- Chats are private to you. Your admin and the Super Admin cannot read them.

### Tips for better answers

- Name the document or party when you can: "In the Separation Agreement, when is the severance paid?"
- Ask one thing at a time. Split long, multi-part questions.
- Use the terms the document uses (for example "contraindications" rather than "when not to take it").
- If you get a refusal, check that the right document is **ready** in your Library and shared with you.

---

## 7. Profile

Select **Profile** in the menu, or your name at the bottom left.

- Edit **Full name** (required), **Job title**, **Department or team** and **Phone**, then select **Save changes**.
- Your email comes from your sign-in account and is changed there.
- The **Membership** box shows your role, organization, workspace and the dates you requested and were approved.

Who sees your details: a member's admin sees them in Manage members; an admin's Super Admin sees the admin's name and
email in Manage admins; a Super Admin's details are seen only by themselves. Profile changes are recorded in the audit
trail by field name only, not the new values.

---

## 8. Audit trail

**Audit trail** lists what happened, newest first. Every event is linked to the one before it by a SHA-256 hash,
so any later change to the history can be detected.

### Sections

| Role | Sections |
| --- | --- |
| Member | All activity · Library · Chats |
| Admin | All activity · Members · Library · Questions & chats · Invite codes |
| Super Admin | All activity · Admins · Organization Code · Organization & profile |

Each section shows a short description of what it covers.

### Filters

- **Search**: person, document title, outcome and similar text.
- **Event**: one kind of event, such as "Document uploaded" or "Question answered".
- **Person**: Anyone, Me, "My admin" (members) or "Everyone but me" (admins and Super Admins), or one named person.
- **From** and **To**: a date range.
- **Reset** clears the filters.

The filters are saved in the page address, so you can bookmark a view or send the link to a colleague who has the
same access.

### Events

Click an event to see who did it, what it affected, its details and its hash. For your own chat events,
**Open this chat** takes you to the chat. **Load older events** shows more.

Questions and answers are recorded as hashes, never as text. Titles of documents you cannot see are shown as
"Private document", and searching for such a title finds nothing.

### Verify hash chain

Select **Verify hash chain** to recompute every event of your organization from the first one.

- **Chain intact** means nothing has been changed or removed.
- **Tampering detected** means an event no longer matches its hash. Contact Onekami at help@onekami.site.

---

## 9. Who can see what

| Item | Owner | Admin | Other members | Super Admin |
| --- | --- | --- | --- | --- |
| A member's private document | Yes | Count only | No | No |
| A member's document shared with the admin | Yes | Yes | No | No |
| An admin's document shared with the whole workspace | Yes | Yes | Yes | No |
| An admin's document shared with chosen members | Yes | Yes | Chosen members only | No |
| An admin's private document | Yes | Yes (owner) | No | No |
| Chats, questions and answers | Author only | No (counts only) | No | No (workspace totals only) |
| Member profile | Yes | Yes (read only) | No | No |
| Anything in another workspace | No | No | No | Counts only |

---

## 10. Sign-in sessions

- You are signed out after **30 minutes** without activity, and after **8 hours** in any case. Sign in again to continue.
- Select the **sign-out** icon next to your name to end your session. On a shared computer, always sign out.
- When an admin or Super Admin suspends you, access stops on your next click.

---

## 11. Troubleshooting

| What you see | What to do |
| --- | --- |
| **Code invalid or expired.** | Check that you used the right kind of code: 64 characters to join as an admin, 32 to join a workspace. Ask for a new code; it may have been rotated, expired or used up. |
| **Too many attempts. Try again later.** | Several wrong codes were entered. Wait 15 minutes, or up to an hour if many wrong codes came from your network, then try again with the correct code. |
| **Waiting for approval** | Your request was sent. Ask your Super Admin or admin to approve it, then select **Check again**. |
| **Access is paused** | Your account or workspace is suspended. Contact your admin (members) or Super Admin (admins). |
| "That sign-in link was already used or has expired." | Select **Sign in** and sign in again. |
| A page says it was not found | That page is not available to your role, or the link is wrong. Use the menu. |
| **This PDF has no text layer (scanned).** | Scanned PDFs are not supported yet. Export the document as a text PDF or DOCX and upload that. |
| **No text found in the file.** | The file is empty or contains only images. |
| A document stays **failed** | The reason is shown under the document. Fix the file and upload it again. |
| **Too many uploads / Too many questions. Try again in a minute.** | You reached the per-minute limit: 60 uploads or 20 questions a minute. Wait a minute. |
| "No documents are ready yet." on Ask | Upload a document in Library, or ask your admin to share one, and wait until it shows **ready**. |
| **The provided documents do not address this.** | Your documents do not answer it. Check that the right document is ready and shared with you, and rephrase with the document's terms. |
| A claim was removed | One sentence failed a check; the rest is verified. Open **verification details** to see why, or ask a narrower question. |
| "This source is no longer available to you." | The document was deleted, or your access to it changed after the answer was given. |
| "This chat does not exist or is not yours." | The chat was deleted, or the link belongs to someone else's chat. |
| An answer takes longer than a minute or shows an error | The answer service may be busy. Try again shortly. If it keeps happening, contact Onekami at help@onekami.site. |

---

## 12. Not available yet

The product design includes the features below. They are not in this preview, so do not rely on them yet.

- Changing who a document is shared with after upload
- Reading scanned PDFs (text recognition)
- Matters (case or patient folders) with access grants and confidentiality levels
- Ethical walls for legal workspaces, and time-limited emergency access for clinical workspaces
- Required passkeys and extra confirmation for admin actions
- A co-owner for the organization and two-person approval for major changes
- Handing a workspace to a new admin, and a holding area for documents of members who leave
- Encryption of documents with a separate key per organization
- Answers that appear sentence by sentence while they are checked
- Email notifications for join requests and approvals

---

## 13. Glossary

| Term | Meaning |
| --- | --- |
| Organization | Your firm, hospital or practice in Cyte |
| Workspace | One team inside the organization, run by one admin and separate from other workspaces |
| Super Admin | The organization owner. Approves admins; never reads documents. |
| Admin | Runs one workspace. Approves members, uploads and shares documents, asks questions. |
| Member | A person in a workspace who asks questions and uploads documents. The technical design calls this role "tenant". |
| Organization Code | 64-character code that lets a person request to become an admin |
| Member invite code | 32-character code that lets a person request to join a workspace |
| Invite link | A link that carries the code, so the person does not have to paste it |
| Lookup ID | The first 8 characters of a code, shown afterwards to identify it. It cannot be used to join. |
| Passage | A section of a document that Cyte searches and cites |
| Citation | The numbered link from a sentence to the passage that supports it |
| Refusal | The answer "The provided documents do not address this." |
| Hash chain | The link between audit events that makes any change to the history detectable |
