# Phase 2 Ground Truth -- Candidate Review

**STATUS: CANDIDATE -- NOT YET VALIDATED GROUND TRUTH.**

Every row below was proposed by an AI agent (Claude) after directly reading real chunk text from the canonical `educopilot_chunks` collection (read-only; nothing was modified). No row has been confirmed by a human reviewer yet. Please review each row and mark it APPROVED, REJECTED, or NEEDS-EDIT before any of this is used as real ground truth for `phase2_multilingual_embedding_evaluation.py`.

Columns: query_id, query, query_language -> source_language, subject, source_type, chunk_id(s), a short excerpt of the actual chunk text, the proposed relevance rationale, and a blank review-status column for you to fill in.

## c_mft_mvt

- **Subject:** operating systems
- **Source language:** english
- **Source type:** pdf
- **Document ID:** `6aa90e314ac03b89c7624ccb`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `f0cc7bc5-bad4-5302-aae1-1e57efe5e5d2`
- **Reviewer notes (from Claude):** Chunk explicitly names MFT (multiple fixed partition) and MVT (multiple variable partition) and lists advantages/disadvantages of each.

**Actual chunk text excerpt (first 500 chars):**

> (Hardware support for relocation and limit registers) According to size of partitions, the multiple partition schemes are divided into two types: i. Multiple fixed partition/ multiprogramming with fixed task(MFT) ii. Multiple variable partition/ multiprogramming with variable task(MVT) i. Multiple fixed partitions: Main memory is divided into a number of static partitions at system generation time. In this case, any process whose size is less than or equal to the partition size can be loaded int

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | What is the difference between multiple fixed partitions (MFT) and multiple variable partitions (MVT)? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | एकाधिक स्थिर विभाजन (MFT) और एकाधिक परिवर्तनीय विभाजन (MVT) में क्या अंतर है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | MFT aur MVT partitioning mein kya difference hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_producer_consumer

- **Subject:** operating systems
- **Source language:** english
- **Source type:** pdf
- **Document ID:** `6aa90e314ac03b89c7624ccb`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `f3c769b8-86c7-5928-aadc-9464f1113f6e`
- **Reviewer notes (from Claude):** Chunk defines the producer-consumer paradigm and the bounded/unbounded buffer setup.

**Actual chunk text excerpt (first 500 chars):**

> Lecture # 17 Process Synchronization A situation where several processes access and manipulate the same data concurrently and the outcome of the execution depends on the particular order in which the access takes place, is called a race condition. Producer-Consumer Problem Paradigm for cooperating processes, producer process produces information that is consumed by a consumer process. To allow producer and consumer processes to run concurrently, we must have available a buffer of items that can 

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | What is the producer-consumer problem in process synchronization? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | प्रोसेस सिंक्रोनाइजेशन में प्रोड्यूसर-कंज्यूमर समस्या क्या है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | Process synchronization mein producer-consumer problem kya hoti hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_process_vs_program

- **Subject:** operating systems
- **Source language:** english
- **Source type:** pdf
- **Document ID:** `6aa72e4416cbab6b27d5f50b`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `8bde1fee-6475-5709-b3d3-df7cc009e665`
- **Reviewer notes (from Claude):** Chunk contains an explicit numbered list contrasting process vs program (static vs dynamic, secondary vs main storage, active vs passive entity, etc.).

**Actual chunk text excerpt (first 500 chars):**

> Lecture #6(UNIT-II) Process Concept  Informally, a process is a program in execution. A process is more than the program code, which is sometimes known as the text section. It also includes the current activity, as represented by the value of the program counter and the contents of the processor's registers. In addition, a process generally includes the process stack, which contains temporary data (such as method parameters, return addresses, and local variables), and a data section, which cont

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | What is the difference between a process and a program? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | प्रोसेस और प्रोग्राम में क्या अंतर है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | Process aur program mein kya farak hota hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_semaphore_wait_signal

- **Subject:** operating systems
- **Source language:** english
- **Source type:** pdf
- **Document ID:** `6aa846698a7bd709c53a5f4e`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `ccda131d-5398-57b1-87ea-a90e73ae79ea`
- **Reviewer notes (from Claude):** Chunk gives the classical pseudocode definitions of wait(S) and signal(S) and states they must execute indivisibly.

**Actual chunk text excerpt (first 500 chars):**

> Lecture # 20 Semaphores The solutions to the critical-section problem presented before are not easy to generalize to more complex problems. To overcome this difficulty, we can use a synchronization tool called a semaphore. A semaphore S is an integer variable that, apart from initialization, is accessed only through two standard atomic operations: wait and signal. These operations were originally termed P (for wait; from the Dutch proberen, to test) and V (for signal; from verhogen, to increment

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | What are the wait and signal operations on a semaphore? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | सेमाफोर पर वेट और सिग्नल ऑपरेशन क्या होते हैं? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | Semaphore ke wait aur signal operations kya hote hain? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_sql_null

- **Subject:** database management systems
- **Source language:** english
- **Source type:** pdf
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Relevant chunk_id(s):** `b1766d23-6160-5557-82a0-6e03804af525`
- **Reviewer notes (from Claude):** Chunk explains three-valued logic (true/false/unknown) for comparisons and boolean connectives involving NULL, and the IS NULL / IS NOT NULL operators.

**Actual chunk text excerpt (first 500 chars):**

> SQL provides a special column value called null to use in such situations. We use null when the column value is either unknown or inapplicable. Using our Sailor table definition, we might enter the row 〈98, Dan, null, 39〉 to represent Dan. The presence of null values complicates many issues, and we consider the impact of null values on SQL in this section. Comparisons Using Null Values Consider a comparison such as rating = 8. If this is applied to the row for Dan, is this condition true or fals

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | How does SQL evaluate comparisons involving NULL values? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | SQL में NULL वैल्यू वाले तुलनात्मक एक्सप्रेशन का मूल्यांकन कैसे होता है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | SQL mein NULL value wale comparisons ka result kya hota hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_sql_transaction_end

- **Subject:** database management systems
- **Source language:** english
- **Source type:** pdf
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Relevant chunk_id(s):** `581137a9-893e-58a0-9137-43c8cd89d235`
- **Reviewer notes (from Claude):** Chunk states a transaction ends via COMMIT WORK or ROLLBACK WORK, and that statements implicitly commit unless autocommit is disabled.

**Actual chunk text excerpt (first 500 chars):**

> Transaction Definition in SQL  Data manipulation language must include a construct for specifying the set of actions that comprise a transaction.  In SQL, a transaction begins implicitly.  A transaction in SQL ends by: Commit work commits current transaction and begins a new one. Rollback work causes current transaction to abort.  In almost all database systems, by default, every SQL statement also commits implicitly if it executes successfully Implicit commit can be turned off by a datab

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | How does a transaction end in SQL? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | SQL में एक ट्रांजैक्शन कैसे समाप्त होता है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | SQL mein transaction kaise end hota hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_os_modules

- **Subject:** operating systems
- **Source language:** hindi
- **Source type:** youtube
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `f404ac22-88f5-591d-b20f-e0502be6ef96`
- **Reviewer notes (from Claude):** ASR transcript uses a government-ministries analogy; states OS has separate modules per function and singles out process management and memory management as the two modules emphasized in this course.

**Actual chunk text excerpt (first 500 chars):**

> नम े ं ट ऑफ इ ं ड ि य ा क ा ग ो ल ह ै म ा न ल ी ज ि ए सबक ा स ा थ सबक ा व ि क ा स । व ो क ै स े ह ो ग ा? 58 मिनिस्ट्रीज हैं। 93 डिपार्टमेंट्स हैं जो डायरेक्ट गवर्नमेंट ऑफ इंडिया को रिपोर्ट करते हैं। हम कह रहे हैं अगर सारे डिपार्टमेंट अच्छे से काम करेंगे तो काम भी ठीक से होगा। ठीक उसी तरह यहां पर भी ऑपरेटिंग सिस्टम में फाइल मैनेजमेंट, प्रोसेस मैनेजमेंट, इनपुट आउटपुट डिवाइस, नेटवर्क, स्टोरेज, सिक्योरिटी हर काम को करने के लिए अलग मॉड्यूल हैं। और अगर ये सारे मॉड्यूल्स फंक्शन सही से काम करेंगे तो ओवर

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | Why does an operating system have separate modules for tasks like file management, process management, and networking? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | ऑपरेटिंग सिस्टम में फाइल मैनेजमेंट, प्रोसेस मैनेजमेंट और नेटवर्किंग जैसे कार्यों के लिए अलग-अलग मॉड्यूल क्यों होते हैं? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | Operating system mein file management, process management aur networking ke liye alag-alag modules kyu hote hain? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_real_time_os

- **Subject:** operating systems
- **Source language:** hindi
- **Source type:** youtube
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `280c2744-c8bb-5f78-854b-52e3b77c8613`
- **Reviewer notes (from Claude):** Uses an air-traffic-control example to define a real-time OS as one that must guarantee task completion within a fixed time constraint.

**Actual chunk text excerpt (first 500 chars):**

> एयरक्राफ्ट का या मान लीजिए एग्जांपल है एटीसी का। है ना? किसी भी समय इंडियन एयर स्पेस के अंदर मान लीजिए देयर आर थाउजेंड्स ऑफ़ एयरक्राफ्ट। मान के लीजिए रियलिटी है भाई थाउजेंड्स ऑफ़ एयरक्राफ्ट होते हैं। तो क्या हमारा सिस्टम हैंग हो सकता है? या अगर कोई एयरक्राफ्ट हमसे रिसोंड करने के लिए बोल रहा है क्या उसमें लैग हो सकता है? उसमें लैग नहीं हो सकता। तो ये कुछ एग्जांपल ऐसे हैं कि सर काम सिर्फ करना नहीं है। गारंटी के साथ इतने फिक्स टाइम कांस्टेंट के अंदर करना है। तो अगर इस तरह की कंडीशन हमारे ऊपर होती है 

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | What is a real-time operating system? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | रियल टाइम ऑपरेटिंग सिस्टम क्या होता है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | Real time operating system kya hota hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_process_stack_contents

- **Subject:** operating systems
- **Source language:** hindi
- **Source type:** youtube
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `15197ab2-7fc0-5cc8-9860-5c0409be66ba`
- **Reviewer notes (from Claude):** States the data section holds global variables, the heap holds runtime dynamic allocation, and the stack (activation record) holds parameters, return addresses, and local variables. NOTE: same underlying concept as c_process_vs_program's English PDF chunk -- deliberately kept as a SEPARATE candidate entry (different source, different chunk) rather than merged, so a reviewer can judge each independently; do not assume these two entries share relevant_chunk_ids.

**Actual chunk text excerpt (first 500 chars):**

> का जितना कोड है वो पूरा कोड है। पीसीबी इससे अलग है। है ना? मैं मेमोरी में आपको प्रोसेस किस तरह से दिखेगा उसकी इमेज दिखा रहा हूं। देन उसके ऊपर आपको मिलेगा डेटा सेक्शन जहां पे ग्लोबल वेरिएबल्स जो है हमारे हैं वो डिक्लेअर होते हैं। उससे ऊपर आपको मिलेगा हीप जहां पे रन टाइम पे अगर डायनेमिक मेमोरी एलोकेशन हम करते हैं तो वो हिप में होता है और जो हमारा पूरा एक्टिवेशन रिकॉर्ड है स्टक वो ऊपर से नीचे चलता है जिसमें पैराटर्स रिटर्न्स वेरिएबल एड्रेसेस वो सारी इनेशन रहती है। अगेन बहुत डिटेल में जाने की जरूरत 

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | What does the stack section of a process contain? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | एक प्रोसेस के स्टैक सेक्शन में क्या होता है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | Process ke stack section mein kya hota hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_sjf_not_implementable

- **Subject:** operating systems
- **Source language:** hindi
- **Source type:** youtube
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `b15a9c9f-c3c6-54ee-a865-5b328b74f755`
- **Reviewer notes (from Claude):** States SJF is not implementable because a process's own CPU burst time is not known in advance, and is used only as a theoretical reference point.

**Actual chunk text excerpt (first 500 chars):**

> ह ै । थ ् य ो र ि ट ि कल आईड ि य ा ह ै । आप ब ो ल े ं ग े इ ं प ् ल ी म े ं ट े बल क ् य ो ं नह ी ं ह ै? भाई सोचो पूरा का पूरा जो एल्गोरिदम है वो इस बात पे टिका हुआ है कि किसका बस टाइम क्या है? लेकिन सवाल ये है जब प्रोसेस एग्जीक्यूशन के लिए आता है क्या प्रोसेस को पहले से पता होता है मेरा बस टाइम क्या है क्या प्रोसेस को पता है कि वो ओवरऑल CPU पे कितने समय के लिए एग्जीक्यूट करेगा ऑब्वियसली नहीं पता होता नहीं पता होता ना सो दैट इज़ अ प्रॉब्लम तो ये ओवरऑल एल्गोरिदम अच्छा है बट क्योंकि बस टाइम हमें नह

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | Why is the Shortest Job First (SJF) scheduling algorithm difficult to implement in practice? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | शॉर्टेस्ट जॉब फर्स्ट (SJF) शेड्यूलिंग एल्गोरिदम को व्यवहार में लागू करना कठिन क्यों है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | SJF scheduling algorithm ko practically implement karna mushkil kyu hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_page_fault_definition

- **Subject:** operating systems
- **Source language:** hindi
- **Source type:** youtube
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `de102609-87b3-5d1d-b5d6-78591df889cd`
- **Reviewer notes (from Claude):** Explains the valid/invalid bit in the page table and defines a page fault as referencing a page whose bit is invalid (not currently in main memory).

**Actual chunk text excerpt (first 500 chars):**

> म े र ा क ौ न स ा प े ज अभ ी म े न म े म ो र ी म े ं क ौ न स ा नह ी ं ह ै । त ो हम क ् य ा करत े ह ै ं? पेज टेबल के अंदर ही एक एडिशनल बिट लगा देते हैं जिसे बोलते हैं वैलिड इनवैलिड बिट। तो जहां-जहां वैलिड बिट की वैल्यू लेट मी से वैलिड है। लेट मी से वन है वहां मान लेते हैं कि ये पेज अभी है। और अगर इनवैलिड है तो मानना पड़ेगा कि वो पेज अभी मेन मेमोरी में नहीं है। अगर हम किसी ऐसे पेज को रेफर कर लेते हैं। सीपीयू ने बोला मेरे को वो पेज चाहिए जो अभी नहीं है। इस सिनेरियो को बोलते है पेज फ़ौल्ट। क्या हो गय

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | What is a page fault? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | पेज फॉल्ट क्या होता है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | Page fault kya hota hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_fcfs_disk_scheduling

- **Subject:** operating systems
- **Source language:** hindi
- **Source type:** youtube
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Relevant chunk_id(s):** `7d131130-e14e-597a-9cb1-f3dc5dad183e`
- **Reviewer notes (from Claude):** Explains FCFS serves disk requests strictly in arrival order regardless of track position, causing more physical head movement than necessary (illustrated with a worked track-number example).

**Actual chunk text excerpt (first 500 chars):**

> टल आईड ि य ा ह ो सकत ा ह ै द ै ट इज़ एफस ी एफएस ज ो हर जगह हम य ू ज़ करत े आए ह ै ं । त ो एफस ी एफएस क ् य ा ब ो ल े ग ा सर? वो यह बोलेगा कि फॉर एग्जांपल अगर यह हमारे पास सारे ट्रैक नंबर हैं तो मैं जैसे यहां शायद दिख भी रहा है। मेरे को फर्क नहीं पड़ता कि आपका कौन सा ट्रैक नंबर आगे है, कौन सा पीछे है या मुझे फिजिकली कितना मूव करना पड़ेगा। जो रिक्वेस्ट पहले आई थी उसको हम पहले आंसर करेंगे। जो बाद में आई थी उसको बाद में आंसर करेंगे। अब ये है तो वैलिड कोई प्रॉब्लम नहीं है इसमें। बट जैसा आप देख रहे हैं 

| query_language | query | proposed relevant? | review status (fill in) |
|---|---|---|---|
| english | What is a drawback of the FCFS disk scheduling algorithm? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hindi | FCFS डिस्क शेड्यूलिंग एल्गोरिदम की एक कमी क्या है? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |
| hinglish | FCFS disk scheduling algorithm ka ek drawback kya hai? | yes (proposed) | ☐ approved / ☐ rejected / ☐ needs edit |

---

## Corpus limitations discovered during construction (for reviewer awareness)

- One YouTube document (`6aaa4cd56eee7990194e5168`, "Introduction to Operating System and its Functions | Lecture 1", 527 chunks) has chunks averaging ~6.7 words each (range 1-10 words) -- far too fragmented for any chunk to stand alone as answerable evidence. Excluded entirely from this candidate set.
- One PDF document (`6aa72df916cbab6b27d5f50a`, 120 chunks) is a Maharashtra CET admissions allotment list (student names/scores/categories), not educational content. Excluded entirely.
- One MP4 document (`6aa90eb64ac03b89c7624cce`) has exactly 1 chunk whose entire text is the single word "you". Excluded entirely.
- No genuine Hinglish-SOURCE content (Hindi words in Roman script as the underlying CONTENT) was found anywhere in the corpus -- a keyword scan of all 1473 non-Devanagari chunks for common Hinglish markers (hai, kya, nahi, matlab, toh, bhai, etc.) found zero matches. All non-Devanagari content is genuinely English. The Hinglish QUERY-language cells above are therefore real (Claude wrote genuine Hinglish queries), but Hinglish as a SOURCE language could not be populated with real content, per this task's explicit instruction not to invent content that is not present. English source -> Hinglish query and Hindi source -> Hinglish query are covered; Hinglish-source rows are not, and are not fabricated.
- The Hindi YouTube transcript (`6aaa7e8c81e2b76728b76bb6`) contains visible ASR noise in places -- some passages are rendered with unnatural letter-by-letter spacing (e.g. "ो द े रह ा ह ै" instead of "जो दे रहा है") immediately before a cleaner re-rendering of the same speech. Every chunk selected for this candidate set was checked to have at least one clean, legible sentence actually supporting the proposed answer, but reviewers should be aware this artifact exists broadly in that document.
- Two OS PDF documents (`6aa72e4416cbab6b27d5f50b` and `6aa72dae16cbab6b27d5f508`) share at least one identical page's text ("Lecture #6(UNIT-II) Process Concept", page 15) -- likely overlapping/duplicate source material. Only one of the two was used per concept in this candidate set; a full ground truth pass may want to check whether some `relevant_chunk_ids` lists should include both documents' copies.