import "server-only";

// The documentation shown at /docs. Written from the project blueprint (section numbers in the comments) and
// checked against what this build does. Server-only: private pages are rendered only for readers whose role allows
// them, so their text must never be bundled into client JavaScript. The client gets titles and links only
// (docsNav below).

export type Tier = "public" | "member" | "admin" | "super_admin";

export type Block =
  | { t: "p"; text: string }
  | { t: "h2"; id: string; text: string }
  | { t: "list"; items: string[] }
  | { t: "steps"; items: string[] }
  | { t: "table"; head: string[]; rows: string[][] }
  | { t: "note"; tone?: "info" | "warn"; text: string }
  | { t: "code"; text: string };

export interface DocPage {
  slug: string;
  title: string;
  summary: string;
  group: string;
  tier: Tier;
  blocks: Block[];
}

export const GROUPS = ["Get started", "Ask and cite", "Documents", "People and access", "Records", "Reference"] as const;

const RANK: Record<Exclude<Tier, "public">, number> = { member: 1, admin: 2, super_admin: 3 };
const ROLE_TIER = { tenant: "member", admin: "admin", super_admin: "super_admin" } as const;

/** Who may read a page: everyone for public pages; otherwise an active account whose role is at or above it. */
export function canRead(tier: Tier, role: keyof typeof ROLE_TIER | null): boolean {
  if (tier === "public") return true;
  if (!role) return false;
  return RANK[ROLE_TIER[role]] >= RANK[tier];
}

export const TIER_LABEL: Record<Exclude<Tier, "public">, string> = {
  member: "members of a workspace",
  admin: "workspace admins",
  super_admin: "Super Admins",
};

const PAGES: DocPage[] = [
  // ------------------------------------------------------------------------------------------------ Get started
  {
    // Blueprint 1.1, 1.2, 11
    slug: "introduction",
    title: "Introduction",
    summary: "What Cyte is, how an answer is produced, and what it will not do.",
    group: "Get started",
    tier: "public",
    blocks: [
      {
        t: "p",
        text: "Cyte answers questions about your legal and medical documents: contracts, case files, regulations, drug labels, guidelines and research. Every sentence of an answer carries a citation to the page and section it came from, and is checked against that passage before anyone sees it. When your documents do not support an answer, Cyte says so instead of guessing.",
      },
      { t: "h2", id: "how-an-answer-is-made", text: "How an answer is made" },
      {
        t: "steps",
        items: [
          "**Search.** Cyte searches only the documents you are allowed to read, with your question and up to three rephrasings of it. Each search combines meaning-based search, word search and exact matching of identifiers, so paraphrases and precise terms (a section number, a drug name, a dose) are both found.",
          "**Rank.** A relevance model reads the question with each candidate passage and keeps only the passages that bear on it, plus the passages just before and after the best ones for context. If nothing is relevant, Cyte refuses without drafting anything.",
          "**Draft.** An AI model drafts an answer from the passages found, and must quote the passage that supports each sentence.",
          "**Verify.** Every sentence goes through ten checks: the quote must appear word for word, numbers and dates must match, and the passage must actually support the claim. A sentence that fails is removed, and the answer says so.",
          "**Record and release.** The answer, the passages it used and an audit event are saved together. Only then is the answer shown.",
        ],
      },
      { t: "h2", id: "what-it-will-not-do", text: "What Cyte will not do" },
      {
        t: "list",
        items: [
          "Give legal or medical advice. It reports what your documents say and where they say it.",
          "Answer from general knowledge. If your documents do not contain the answer, you get “The provided documents do not address this.”",
          "Show a sentence it could not check.",
        ],
      },
      {
        t: "note",
        text: "New to Cyte? Read [How Cyte is organized](/docs/how-cyte-is-organized), then [Sign up and join](/docs/sign-up-and-join).",
      },
    ],
  },
  {
    // Blueprint 5.1, 5.2
    slug: "how-cyte-is-organized",
    title: "How Cyte is organized",
    summary: "Organizations, workspaces and the three roles.",
    group: "Get started",
    tier: "public",
    blocks: [
      {
        t: "code",
        text: "Organization  (your firm or hospital)       run by the Super Admin\n├── Workspace A  (for example Litigation)   run by Admin A\n│   └── Members A1, A2 …\n└── Workspace B  (for example Cardiology)   run by Admin B\n    └── Members B1 …",
      },
      {
        t: "list",
        items: [
          "An **organization** is one customer, such as a law firm, hospital or practice. It has one **Super Admin**.",
          "A **workspace** is a team inside the organization, run by exactly one **Admin**. Workspaces cannot see each other.",
          "A **member** belongs to one workspace, asks questions and uploads their own documents.",
          "Each person belongs to one organization and holds one role. Changing role means leaving and joining again, so a role can never be raised from inside the product.",
        ],
      },
      { t: "h2", id: "roles", text: "What each role can do" },
      {
        t: "table",
        head: ["Task", "Super Admin", "Admin", "Member"],
        rows: [
          ["Create the organization", "Yes", "No", "No"],
          ["Generate the Organization Code; approve and suspend admins", "Yes", "No", "No"],
          ["See admins and usage totals", "Yes", "No", "No"],
          ["Generate the member invite code; approve and suspend members", "No", "Own workspace", "No"],
          ["See members' profiles and usage counts", "No", "Own workspace", "No"],
          ["Upload documents and ask questions", "No", "Yes", "Yes"],
          ["Share documents", "No", "Whole workspace or chosen members", "With their admin"],
          ["Read a member's private documents", "No", "No", "Their own only"],
          ["Read someone else's chats", "No", "No", "No"],
          ["Verify the audit hash chain", "Yes", "Yes", "Yes"],
        ],
      },
      {
        t: "p",
        text: "The Super Admin governs the organization but never reads workspace documents, members' details or questions. The database itself holds no access rule that would let that role read them.",
      },
    ],
  },
  {
    // Blueprint 7.1-7.4
    slug: "sign-up-and-join",
    title: "Sign up and join",
    summary: "Create an organization, join as an admin, or join a workspace.",
    group: "Get started",
    tier: "public",
    blocks: [
      {
        t: "p",
        text: "Select **Get started** at the top right of the website and create your account, or **Sign in** if you have one. The first time, Cyte asks how you will use it and shows three choices. The choice only opens a form: your role is decided by the code you enter, checked on our side.",
      },
      { t: "h2", id: "create", text: "Create an organization" },
      {
        t: "steps",
        items: [
          "Choose **Create an organization**.",
          "Enter the organization's name and choose its type: legal, medical or both. The type sets the example questions shown when you ask.",
          "Select **Create organization**. You are its Super Admin and land on Manage admins.",
        ],
      },
      { t: "h2", id: "join-as-admin", text: "Join as an admin" },
      {
        t: "steps",
        items: [
          "Get the 64-character Organization Code, or an invite link, from your Super Admin.",
          "Open the link (the code is filled in) or choose **Join as an admin** and paste it. Dashes, spaces and lower case are fine.",
          "Name your workspace, for example “Litigation” or “Cardiology”, and select **Send request**.",
          "Wait for approval. **Check again** refreshes; **Withdraw request** cancels.",
        ],
      },
      { t: "h2", id: "join-as-member", text: "Join a workspace" },
      {
        t: "steps",
        items: [
          "Get the 32-character invite code, or an invite link, from your workspace admin.",
          "Open the link or choose **Join a workspace** and paste the code, then select **Continue**.",
          "Check the workspace, organization and admin shown. Checking does not use up the code.",
          "Select **Request to join** and wait for your admin to approve you.",
        ],
      },
      {
        t: "note",
        text: "Until you are approved you see a waiting page and have no access to any documents.",
      },
    ],
  },
  {
    // Blueprint 7.6
    slug: "codes-and-approvals",
    title: "Codes and approvals",
    summary: "How invite codes work and why every join is approved by a person.",
    group: "Get started",
    tier: "public",
    blocks: [
      {
        t: "p",
        text: "People join with a one-time code and are then approved by a person. A code on its own never grants access: a leaked code can only create a request that the owner of the code rejects.",
      },
      {
        t: "table",
        head: ["", "Organization Code", "Member invite code"],
        rows: [
          ["Length", "64 characters", "32 characters"],
          ["Made by", "The Super Admin", "A workspace admin"],
          ["Lets a person", "Request to become an admin", "Request to join that workspace"],
          ["Valid for", "30 days, up to 25 requests", "90 days, up to 100 requests"],
        ],
      },
      { t: "h2", id: "safety", text: "How codes are protected" },
      {
        t: "list",
        items: [
          "A new code is shown **once**. Afterwards only its first 8 characters (the lookup ID), expiry date and number of uses are shown.",
          "Codes are stored only as keyed hashes, never as readable text.",
          "The last character is a check character, so the form catches most typing mistakes before sending.",
          "Invite links carry the code after a “#”, which browsers never send to a server; the page removes it from the address bar.",
          "A wrong, expired or used-up code always gives the same message, “Code invalid or expired.”, so a guesser learns nothing.",
          "After 5 wrong codes in 15 minutes, or 20 from one network in an hour, further attempts are blocked for a while.",
          "**Rotate code** stops the old code at once. Rotate whenever a code may have been shared too widely.",
        ],
      },
    ],
  },

  // ------------------------------------------------------------------------------------------------ Ask and cite
  {
    // Blueprint 11.3, 11.5, 17.2
    slug: "asking-questions",
    title: "Asking questions",
    summary: "Ask, follow up, and get better answers.",
    group: "Ask and cite",
    tier: "member",
    blocks: [
      {
        t: "steps",
        items: [
          "Select **Ask** in the sidebar. Click an example question, or type your own.",
          "Press **Enter** to send (Shift+Enter adds a line). Questions can be up to 2,000 characters.",
          "Wait while Cyte searches, drafts and checks. Most answers take 5 to 20 seconds; nothing is shown until every sentence has been checked.",
        ],
      },
      {
        t: "p",
        text: "Answers use only the documents you can read: your own, those shared with you, and those shared with your whole workspace.",
      },
      { t: "h2", id: "follow-ups", text: "Follow-up questions" },
      {
        t: "p",
        text: "Ask follow-ups in the same chat, as you would with a colleague: “and what must the Executive sign first?” Cyte rewrites the follow-up into a complete question using the conversation, shows it under your question as “Searched as: …”, and answers it from your documents, not from its earlier answers.",
      },
      { t: "h2", id: "tips", text: "Tips for better answers" },
      {
        t: "list",
        items: [
          "Name the document or party: “In the Separation Agreement, when is the severance paid?”",
          "Ask one thing at a time; split long, multi-part questions.",
          "Use the document's own words, for example “contraindications” rather than “when not to take it”.",
          "If you get a refusal, check in your Library that the right document is **ready** and shared with you.",
        ],
      },
      {
        t: "note",
        tone: "warn",
        text: "You can ask up to 20 questions a minute. Cyte reports what your documents say; it does not give legal or medical advice.",
      },
    ],
  },
  {
    // Blueprint 11.6, 17.2
    slug: "reading-answers",
    title: "Reading an answer",
    summary: "Citations, the source panel, refusals, removed claims and the ten checks.",
    group: "Ask and cite",
    tier: "member",
    blocks: [
      {
        t: "list",
        items: [
          "**Numbers after sentences** are citations. Click one to open the source panel: the document, section and page, with the exact passage highlighted.",
          "**Source cards** below the answer list every cited document.",
          "**“The provided documents do not address this.”** means nothing you can read supports an answer. If only part of the question is answered, this sentence follows that part.",
          "**“A claim in this answer could not be verified and was removed”** marks a sentence that failed a check. The reason is shown; the rest of the answer is still verified.",
          "**“This source is no longer available to you”** in the source panel means the document was deleted, or your access changed, after the answer was given.",
        ],
      },
      { t: "h2", id: "the-ten-checks", text: "The ten checks" },
      {
        t: "p",
        text: "Open **verification details** (the line with the shield, such as “4 sentences verified”) to see each check for each sentence, how the sources were found (the phrasings searched, how many passages were considered and kept, and the time each step took) and the model that drafted the answer.",
      },
      {
        t: "table",
        head: ["Check", "What it confirms"],
        rows: [
          ["Citation format", "The citation points to a real source of this answer"],
          ["Source was retrieved for this question", "Only passages found for this question are cited"],
          ["Source unchanged since retrieval", "The passage did not change between search and answer"],
          ["Sentence is cited", "Every sentence that states a fact has a citation"],
          ["Quoted text found in source", "The supporting quote appears word for word in the passage"],
          ["Numbers and dates match the source", "Every number, date, amount and dosage appears in the passage"],
          ["Wording supported by the source", "The sentence's key terms come from the passage"],
          ["Source entails the claim", "A second, stricter review confirms the passage supports the claim"],
          ["Refusal wording", "A “does not address” reply is exact and stands alone"],
          ["Citation resolves to a page and section", "The citation leads to a real place in the document"],
        ],
      },
      {
        t: "p",
        text: "The checks run on the original document text, not on the model's copy of it. A check can only remove a sentence; nothing can approve a sentence that another check rejected.",
      },
    ],
  },
  {
    // Blueprint 17.2 (chat surface)
    slug: "chats",
    title: "Chats",
    summary: "Keep, rename and delete conversations. Chats are private.",
    group: "Ask and cite",
    tier: "member",
    blocks: [
      {
        t: "list",
        items: [
          "The list on the left groups your chats by Today, Yesterday, Previous 7 days and Older.",
          "**New chat** starts a fresh conversation. A new chat is named after its first question.",
          "Hover over a chat to rename it (pencil) or delete it (bin, then **Delete**).",
          "On the Ask page, **Continue where you left off** opens your latest chat.",
        ],
      },
      {
        t: "note",
        text: "Chats are private to you. Your admin and the Super Admin cannot read them; they see only how many questions you asked. The audit trail records questions as hashes, never as text.",
      },
    ],
  },

  // ------------------------------------------------------------------------------------------------ Documents
  {
    // Blueprint 11.1
    slug: "how-documents-are-read",
    title: "How documents are read",
    summary: "Supported files, passages, and what happens to scanned pages.",
    group: "Documents",
    tier: "public",
    blocks: [
      {
        t: "table",
        head: ["Format", "Notes"],
        rows: [
          ["PDF", "Must have selectable text. Scanned pages are reported and skipped, never guessed."],
          ["Word (DOCX)", "Headings, paragraphs and tables are read."],
          ["HTML", "Page structure is used; scripts and styles are ignored."],
          ["XML", "Journal articles (JATS), FDA drug labels (SPL) and US federal regulations (eCFR)."],
          ["Plain text (TXT, MD)", "Split into paragraphs."],
        ],
      },
      { t: "p", text: "Files can be up to 25 MB. Cyte checks a file's real type from its contents, not its name." },
      { t: "h2", id: "passages", text: "Passages" },
      {
        t: "p",
        text: "Cyte splits each document along the way it is written: headings, sections, clauses and pages. Each passage keeps its section title and page numbers, so a citation can say “§3 Severance Benefit · p. 2”. A document without headings is split into paragraphs, and the Library says so.",
      },
      {
        t: "p",
        text: "Indexing is all or nothing: a document becomes **ready** only when every passage has been processed. If anything fails, it is marked **failed** with the reason, and none of it is searchable.",
      },
    ],
  },
  {
    // Blueprint 5.4, 17.2 (library)
    slug: "library",
    title: "Your library",
    summary: "Upload documents, share them with your admin, and read the Access column.",
    group: "Documents",
    tier: "member",
    blocks: [
      {
        t: "steps",
        items: [
          "Open **Library**. Drag files onto the upload area or select **Choose files**.",
          "Decide whether to tick **Share with my workspace admin** before uploading. Sharing cannot be changed afterwards; to change it, delete the document and upload it again.",
          "Wait until the document shows **ready**, then ask questions about it.",
        ],
      },
      {
        t: "p",
        text: "Your uploads are private by default: only you can search them, and your admin cannot open them. Members cannot share with other members.",
      },
      { t: "h2", id: "access-column", text: "The Access column" },
      {
        t: "table",
        head: ["Badge", "Meaning"],
        rows: [
          ["Private", "Only you can see it"],
          ["Shared by you, with your admin", "You shared it with your admin"],
          ["Shared by admin, with you", "Your admin shared it with you by name"],
          ["Shared by admin, with the whole workspace", "Everyone in your workspace can search it"],
        ],
      },
      { t: "h2", id: "delete", text: "Deleting" },
      {
        t: "p",
        text: "You can delete your own documents. A deleted document disappears from search at once; past answers that cited it stay in your chats, with the source marked as no longer available.",
      },
      { t: "note", tone: "warn", text: "You can upload up to 60 files a minute." },
    ],
  },
  {
    // Blueprint 5.4, 5.8
    slug: "sharing-in-a-workspace",
    title: "Sharing in a workspace",
    summary: "Share with the whole workspace or chosen members, and what you see of members' files.",
    group: "Documents",
    tier: "admin",
    blocks: [
      {
        t: "p",
        text: "As an admin, you choose who can use each upload under **Who can use these documents?** before uploading:",
      },
      {
        t: "table",
        head: ["Choice", "Who can search it"],
        rows: [
          ["Whole workspace", "Every member, including members who join later"],
          ["Selected members", "Only the active members you tick (Select all and Clear help)"],
          ["Only me", "Only you"],
        ],
      },
      {
        t: "p",
        text: "Sharing is set at upload. To change it, delete the document and upload it again. You can delete your own documents and any document shared with the whole workspace.",
      },
      { t: "h2", id: "members-files", text: "Members' documents" },
      {
        t: "list",
        items: [
          "A member's documents are private to them. You see how many private documents they have, never the documents themselves.",
          "Documents a member shares with you appear in your Library as **Shared by member** and can be searched by you.",
          "You cannot read a member's chats, questions or answers; you see the number of questions and approximate model usage.",
        ],
      },
      {
        t: "note",
        text: "These limits are enforced by the database, not by hiding buttons: there is no path in the product by which an admin can read a member's private document.",
      },
    ],
  },

  // ------------------------------------------------------------------------------------------------ People and access
  {
    // Blueprint 5.4
    slug: "who-can-see-what",
    title: "Who can see what",
    summary: "The access rules for documents, chats and profiles.",
    group: "People and access",
    tier: "public",
    blocks: [
      {
        t: "table",
        head: ["Item", "Owner", "Admin", "Other members", "Super Admin"],
        rows: [
          ["A member's private document", "Yes", "Count only", "No", "No"],
          ["A member's document shared with the admin", "Yes", "Yes", "No", "No"],
          ["An admin's document shared with the whole workspace", "Yes", "Yes", "Yes", "No"],
          ["An admin's document shared with chosen members", "Yes", "Yes", "Chosen members only", "No"],
          ["Chats, questions and answers", "Author only", "Counts only", "No", "Totals only"],
          ["A member's profile", "Yes", "Read only", "No", "No"],
          ["Anything in another workspace", "No", "No", "No", "Counts only"],
        ],
      },
      { t: "h2", id: "how-its-decided", text: "How access is decided" },
      {
        t: "steps",
        items: [
          "If your account, workspace or organization is not active, access is denied.",
          "A document you own is yours to read.",
          "A document shared with your whole workspace can be read by everyone in it.",
          "A document shared with you by name can be read by you.",
          "Everything else is denied.",
        ],
      },
      {
        t: "p",
        text: "This decision is made by the database for every document, passage and answer, so a mistake on one screen cannot expose another person's or team's documents.",
      },
    ],
  },
  {
    // Blueprint 6 (membership states), 7.4, 7.7, 17.2 (Manage Tenants)
    slug: "managing-members",
    title: "Managing members",
    summary: "Invite, approve, suspend and understand member usage.",
    group: "People and access",
    tier: "admin",
    blocks: [
      { t: "h2", id: "invite", text: "Invite members" },
      {
        t: "steps",
        items: [
          "Open **Manage members** and select **Generate code** in the Member invite code panel.",
          "Copy the code or the invite link. It is shown only once.",
          "Send it privately. It works for 90 days and up to 100 requests. **Rotate code** stops it at once.",
        ],
      },
      { t: "h2", id: "approve", text: "Approve and manage" },
      {
        t: "table",
        head: ["Status", "Meaning", "Actions"],
        rows: [
          ["pending", "Waiting for your decision; no access", "Approve, Reject"],
          ["active", "Full access to the workspace", "Suspend"],
          ["suspended", "No access; data kept", "Reactivate"],
          ["rejected", "Request declined", "None"],
        ],
      },
      {
        t: "p",
        text: "Suspending takes effect on the member's next click. Nothing is deleted.",
      },
      { t: "h2", id: "columns", text: "The members table" },
      {
        t: "table",
        head: ["Column", "Meaning"],
        rows: [
          ["Private documents", "Documents only the member can see. A count; you cannot open them."],
          ["Shared with you", "Documents the member shared with you"],
          ["Shared by you", "Documents you shared with the member by name, plus all you shared with the whole workspace"],
          ["Questions", "Every question asked, not the number of chats"],
          ["Tokens", "Approximate model usage for their questions; search is not counted"],
        ],
      },
      {
        t: "p",
        text: "Click a member to see their profile (email, job title, department, phone, dates) and usage. You can read a profile but not edit it.",
      },
    ],
  },
  {
    // Blueprint 7.3, 7.7, 17.2 (Manage Admins)
    slug: "managing-admins",
    title: "Managing admins",
    summary: "The Organization Code, approving admins, and what suspension does.",
    group: "People and access",
    tier: "super_admin",
    blocks: [
      { t: "h2", id: "invite", text: "Invite admins" },
      {
        t: "steps",
        items: [
          "Open **Manage admins** and select **Generate code** in the Organization Code panel.",
          "Copy the code or invite link (shown once) and send it to the people who will run workspaces.",
          "It works for 30 days and up to 25 requests. Rotate it whenever it may have been shared too widely.",
        ],
      },
      { t: "h2", id: "approve", text: "Approve, suspend, reactivate" },
      {
        t: "p",
        text: "Each request shows the person and the workspace name they chose. Approving opens their workspace; rejecting removes the pending workspace.",
      },
      {
        t: "list",
        items: [
          "**Suspending an admin freezes their whole workspace**: the admin and every member lose access on their next click. No data is deleted.",
          "**Reactivating** restores the admin and the members who lost access through the freeze. Members the admin had suspended individually stay suspended.",
        ],
      },
      { t: "h2", id: "columns", text: "The admins table" },
      {
        t: "table",
        head: ["Column", "Meaning"],
        rows: [
          ["Members", "Active members, plus pending requests as “+n”"],
          ["Documents", "Documents in the workspace, as a count"],
          ["Questions (30 d)", "Questions asked in the workspace over the last 30 days"],
          ["Last active", "When the admin last used Cyte"],
        ],
      },
    ],
  },
  {
    // Blueprint 5.3, 5.9
    slug: "the-owners-role",
    title: "The organization owner's role",
    summary: "What a Super Admin governs, and the content boundary they cannot cross.",
    group: "People and access",
    tier: "super_admin",
    blocks: [
      {
        t: "p",
        text: "As Super Admin you own the organization: you decide who runs each workspace and you see how the organization uses Cyte. You stay out of the content itself.",
      },
      { t: "h2", id: "boundary", text: "The content boundary" },
      {
        t: "p",
        text: "The boundary holds at three levels, so a fault in one cannot expose content:",
      },
      {
        t: "steps",
        items: [
          "**Routes.** Your account has no route to Ask, Library or any workspace page; they answer “not found”.",
          "**Services.** No part of the product looks up documents, members or questions for your role.",
          "**Database.** No access rule lets your role read documents, passages, members' details or chats, so the database returns nothing even if asked.",
        ],
      },
      { t: "h2", id: "good-practice", text: "Good practice" },
      {
        t: "list",
        items: [
          "Approve only people you know, and reject requests you did not expect.",
          "Rotate the Organization Code after onboarding a group of admins.",
          "If you also want to work with documents, sign up a second, separate account and join as an admin. Keep the two accounts on different email addresses.",
          "Check the audit trail and run **Verify hash chain** from time to time.",
        ],
      },
    ],
  },
  {
    // Blueprint 17.1 (account)
    slug: "profile",
    title: "Your profile",
    summary: "Your name, job title, department and phone, and who sees them.",
    group: "People and access",
    tier: "member",
    blocks: [
      {
        t: "steps",
        items: [
          "Select **Profile** in the sidebar, or your name at the bottom left.",
          "Edit your full name (required), job title, department and phone.",
          "Select **Save changes**.",
        ],
      },
      {
        t: "list",
        items: [
          "Your email comes from your sign-in account and is changed there.",
          "Your workspace admin can read your profile in Manage members, but cannot edit it.",
          "Profile changes are recorded in the audit trail by field name only, never the new values.",
        ],
      },
    ],
  },

  // ------------------------------------------------------------------------------------------------ Records
  {
    // Blueprint 13
    slug: "audit-trail",
    title: "Your audit trail",
    summary: "What is recorded about you, the filters, and verifying the record.",
    group: "Records",
    tier: "member",
    blocks: [
      {
        t: "p",
        text: "**Audit trail** lists what happened, newest first: your joining and approval, profile changes, uploads, shares, indexing, deletions, chats and answers. Each event is chained to the one before it with SHA-256, and the database refuses any change to past events.",
      },
      { t: "h2", id: "sections", text: "Sections" },
      {
        t: "table",
        head: ["Section", "Shows"],
        rows: [
          ["All activity", "Everything about you in your workspace"],
          ["Library", "Your uploads, indexing and deletions, and documents your admin shared with you"],
          ["Chats", "Chats you started, renamed or deleted, and every question you asked"],
        ],
      },
      { t: "h2", id: "filters", text: "Filters" },
      {
        t: "list",
        items: [
          "**Search** across people, document titles and outcomes.",
          "**Event**, **Person** (Anyone, Me or My admin) and a **From/To** date range.",
          "Filters are kept in the page address, so a view can be bookmarked.",
          "Click an event for its details and hash; for your chats, **Open this chat** takes you there.",
        ],
      },
      { t: "h2", id: "verify", text: "Verify the record" },
      {
        t: "p",
        text: "**Verify hash chain** recomputes every event of your organization from the first one. “Chain intact” means nothing was changed or removed. “Tampering detected” means an event no longer matches its hash; contact help@onekami.site.",
      },
    ],
  },
  {
    // Blueprint 13, 5.2 (audit by role)
    slug: "workspace-audit",
    title: "Workspace audit",
    summary: "The admin's view of the workspace record, and what stays hidden.",
    group: "Records",
    tier: "admin",
    blocks: [
      {
        t: "table",
        head: ["Section", "Shows"],
        rows: [
          ["All activity", "Every event in your workspace"],
          ["Members", "Join requests, approvals, suspensions and profile changes"],
          ["Library", "Uploads, shares, indexing and deletions"],
          ["Questions & chats", "Who asked how many questions and with what outcome"],
          ["Invite codes", "Code rotations and rejected code attempts"],
        ],
      },
      {
        t: "list",
        items: [
          "**Person** can be set to any member, to you, or to everyone but you.",
          "Questions and answers are recorded as hashes, never as text.",
          "Titles of members' private documents appear as “Private document”, and searching for such a title finds nothing.",
        ],
      },
    ],
  },
  {
    // Blueprint 13, 5.3
    slug: "organization-audit",
    title: "Organization audit",
    summary: "The Super Admin's record of admins, codes and the organization.",
    group: "Records",
    tier: "super_admin",
    blocks: [
      {
        t: "table",
        head: ["Section", "Shows"],
        rows: [
          ["All activity", "Organization-level events"],
          ["Admins", "Admin join requests and your decisions"],
          ["Organization Code", "Code rotations and rejected code attempts"],
          ["Organization & profile", "Organization changes and your profile updates"],
        ],
      },
      {
        t: "p",
        text: "Workspace content never appears in your audit trail. **Verify hash chain** still checks every event of the organization, including those you cannot see, and tells you how many are in your view.",
      },
      {
        t: "note",
        tone: "warn",
        text: "If verification ever reports tampering, do not change anything else; contact help@onekami.site with the time you ran the check.",
      },
    ],
  },

  // ------------------------------------------------------------------------------------------------ Reference
  {
    // Blueprint 8, 10, 13, 11.8
    slug: "security",
    title: "Security and privacy",
    summary: "Isolation, sign-in, audit, and where your data is processed.",
    group: "Reference",
    tier: "public",
    blocks: [
      {
        t: "list",
        items: [
          "**Isolation in the database.** PostgreSQL row-level security decides what each person may read, for every document, passage, answer and share. With no signed-in person, it returns nothing.",
          "**Sign-in.** Through Auth0. Access tokens stay on our server and never reach your browser. Sessions end after 30 minutes without activity, and after 8 hours in any case.",
          "**Roles from our database.** Your role and status are read from our database on every request, so a suspension takes effect on the next click.",
          "**Strict page security.** Every page runs under a strict content security policy that blocks injected scripts.",
          "**Audit.** Every event is hash-chained and protected against edits in the database.",
        ],
      },
      { t: "h2", id: "processing", text: "Where your data is processed" },
      {
        t: "p",
        text: "During early access, document text is sent to Google to make it searchable, and the passages behind each question are sent to the configured AI model to draft the answer. Before you upload real client or patient records, talk to us at contact@onekami.site about hosting and data agreements.",
      },
    ],
  },
  {
    slug: "troubleshooting",
    title: "Troubleshooting",
    summary: "Messages you may see, and what to do.",
    group: "Reference",
    tier: "public",
    blocks: [
      {
        t: "table",
        head: ["Message", "What to do"],
        rows: [
          ["Code invalid or expired.", "Check you used the right kind of code (64 characters for admins, 32 for members). Ask for a new one."],
          ["Too many attempts. Try again later.", "Wait 15 minutes, or up to an hour if many wrong codes came from your network."],
          ["Waiting for approval", "Ask your Super Admin or admin to approve you, then select Check again."],
          ["Access is paused", "Your account or workspace is suspended. Contact your admin (members) or Super Admin (admins)."],
          ["That sign-in link was already used or has expired.", "Sign in again."],
          ["Page not found", "The page is not available to your role, or the link is wrong. Use the menu."],
          ["This PDF has no text layer (scanned).", "Upload a PDF with selectable text, or a Word file."],
          ["No text found in the file.", "The file is empty or contains only images."],
          ["Too many uploads / questions. Try again in a minute.", "Limits are 60 uploads and 20 questions a minute."],
          ["The provided documents do not address this.", "Check that the right document is ready and shared with you, then rephrase with its terms."],
          ["A claim … was removed", "One sentence failed a check; the rest is verified. Open verification details to see why."],
        ],
      },
      { t: "p", text: "Still stuck? Email help@onekami.site." },
    ],
  },
  {
    slug: "roadmap",
    title: "Not available yet",
    summary: "Designed features that are not in this version.",
    group: "Reference",
    tier: "public",
    blocks: [
      { t: "p", text: "These are part of Cyte's design but not in this version. Please do not rely on them yet." },
      {
        t: "list",
        items: [
          "Changing who a document is shared with after upload",
          "Reading scanned PDFs (text recognition)",
          "Matters (case or patient folders) with access grants and confidentiality levels",
          "Ethical walls for legal workspaces, and time-limited emergency access for clinical workspaces",
          "Required passkeys and extra confirmation for admin actions",
          "A co-owner and two-person approval for major organization changes",
          "Handing a workspace to a new admin, and a holding area for documents of members who leave",
          "Encryption of documents with a separate key per organization",
          "Answers that appear sentence by sentence while they are checked",
          "Email notifications for join requests and approvals",
        ],
      },
    ],
  },
  {
    slug: "glossary",
    title: "Glossary",
    summary: "The terms used across Cyte.",
    group: "Reference",
    tier: "public",
    blocks: [
      {
        t: "table",
        head: ["Term", "Meaning"],
        rows: [
          ["Organization", "Your firm, hospital or practice in Cyte"],
          ["Workspace", "One team inside the organization, run by one admin and separate from other workspaces"],
          ["Super Admin", "The organization owner. Approves admins; never reads documents."],
          ["Admin", "Runs one workspace. Approves members, shares documents, asks questions."],
          ["Member", "A person in a workspace who asks questions and uploads documents"],
          ["Organization Code", "64-character code to request to become an admin"],
          ["Member invite code", "32-character code to request to join a workspace"],
          ["Lookup ID", "The first 8 characters of a code, shown afterwards to identify it; it cannot be used to join"],
          ["Passage", "A section of a document that Cyte searches and cites"],
          ["Citation", "The numbered link from a sentence to its supporting passage"],
          ["Refusal", "The answer “The provided documents do not address this.”"],
          ["Hash chain", "The link between audit events that makes any change to the record detectable"],
        ],
      },
    ],
  },
];

export function getDoc(slug: string): DocPage | undefined {
  return PAGES.find((p) => p.slug === slug);
}

export interface NavItem {
  slug: string;
  title: string;
  summary: string;
}

/** Titles and links only, in reading order, grouped. Safe to pass to client components: no tier, no content. */
export function docsNav(): { group: string; items: NavItem[] }[] {
  return GROUPS.map((group) => ({
    group,
    items: PAGES.filter((p) => p.group === group).map(({ slug, title, summary }) => ({ slug, title, summary })),
  }));
}

export function neighbours(slug: string): { prev?: NavItem; next?: NavItem } {
  const flat = docsNav().flatMap((g) => g.items);
  const i = flat.findIndex((p) => p.slug === slug);
  return { prev: flat[i - 1], next: flat[i + 1] };
}
