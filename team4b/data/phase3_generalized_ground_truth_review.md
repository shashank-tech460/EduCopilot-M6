# Phase 3 Generalized Ground Truth -- Candidate Review

**THIS IS A CANDIDATE DATASET.**
**NO ENTRY HAS BEEN HUMAN-VALIDATED.**

This is a GENERALIZED, domain-agnostic benchmark: it covers every real usable content source currently in the `educopilot_chunks` corpus (both Operating Systems and Database Management Systems content actually present), not a subject-specific one. Every row was proposed by an AI agent (Claude) after directly reading real chunk text (read-only; nothing in Qdrant/MongoDB/Redis was modified). Please review each row and mark it APPROVED, REJECTED, or NEEDS-EDIT before any of this is used as real ground truth for `phase2_multilingual_embedding_evaluation.py`.

This file is **additive** to `phase2_ground_truth_candidate.json` / `phase2_ground_truth_candidate_review.md` (Phase 3's earlier, OS/DBMS-only draft) -- neither of those files was deleted or modified.

## Phase 3.1 Reconciliation (2026-09-17)

An architectural review flagged 6 issues in the original 75-entry draft. All are addressed below. **Status remains `CANDIDATE_NOT_VALIDATED` on every entry -- nothing in this pass was approved.** Entry count is unchanged at 75.

| # | Concept | Issue | Resolution |
|---|---|---|---|
| A | `c_mft_mvt` | `query_type` was `advantage_disadvantage`, should be `comparison` | Fixed on all 3 language variants. |
| B | `c_sjf_difficulty` | Query wording ("can't be implemented" / "क्यों नहीं किया जा सकता") overstated an absolute impossibility claim | Reworded to "difficult to implement in practice" framing on all 3 variants; rationale reworded to match. |
| C | `c_memory_hierarchy_locality` | Needed re-verification against the complete chunk (not just the excerpt) | **RESOLVED (final correction, Qdrant now reachable):** the complete chunk introduces "locality of reference" and gives size-ratio context but is cut off before explaining it. Live scroll of the source document found its real continuation, `1e2576b8-b408-5ded-9144-2d977076f961`, which completes the explanation (showroom/godown/factory analogy, temporal + spatial locality named explicitly). Added to `relevant_chunk_ids` alongside the original chunk. `review_flag` updated to `RE_VERIFIED_SUFFICIENT`. A third same-timestamp chunk (`29d10e3f-8811-5937-999e-db01f7019a02`, unrelated topic) was confirmed irrelevant and NOT added. |
| D | `c_transaction_isolation_levels` | Needed re-verification against the complete chunk | **Re-verified and found SUFFICIENT** (this chunk's complete text was already fetched earlier in this session, before Qdrant became unreachable) -- all four isolation levels and the full anomaly table are explicitly present. Flagged `review_flag: RE_VERIFIED_SUFFICIENT`. No chunk change. |
| E | `c_sql_query_evaluation_steps` | Needed re-verification against the complete chunk | **Re-verified and found SUFFICIENT** -- all four conceptual evaluation steps are explicitly present verbatim. Flagged `review_flag: RE_VERIFIED_SUFFICIENT`. No chunk change. |
| F | `c_workspace_wide_scheduling_algorithms` | Query said "CPU scheduling algorithms" but the cited evidence includes FCFS *disk* scheduling | Query corrected to "What scheduling algorithms are discussed in this workspace's course materials?" (dropped "CPU"); `subject` corrected from `cpu scheduling` to `scheduling` to match. Workspace-wide, multi-document nature preserved exactly as before. |

**Additionally found and corrected during the multi-chunk/multi-document genuineness check (items 4-5 of the reconciliation instructions):** `c_process_memory_cross_document_hard`'s rationale claimed "neither chunk is fully complete on its own." Re-reading the complete Hindi chunk text showed this was wrong -- the Hindi chunk alone already covers all three memory regions (data section, heap, stack). Only the English PDF chunk is partial (missing the heap). The entry is **kept** (per instruction not to remove valid multi-document/cross-language cases merely because they're difficult), but its rationale was corrected to accurately describe the evidence relationship instead of overclaiming necessity.

**Not changed:** `c_sjf_cross_document_hard` and `c_workspace_wide_scheduling_algorithms` were re-examined for the same overclaiming risk and found to already be honestly framed ("either or both" / genuinely requires enumerating across documents for a complete answer) -- no rationale correction was needed for those two.

**Update (Phase 3.1 final correction, same day):** `c_memory_hierarchy_locality` (issue C above) is now fully resolved -- see its section below. No open items remain from this reconciliation pass.

---

## c_mft_mvt

- **Domain:** operating systems
- **Subject:** memory management
- **Source language:** english
- **Source type:** pdf
- **Query type:** comparison *(corrected in Phase 3.1 -- was `advantage_disadvantage`; see reconciliation notes above)*
- **Difficulty:** easy
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa90e314ac03b89c7624ccb`
- **Relevant chunk_id(s):** `f0cc7bc5-bad4-5302-aae1-1e57efe5e5d2`
- **Reviewer notes (from Claude):** Chunk explicitly names MFT and MVT and lists advantages/disadvantages of each.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `f0cc7bc5-bad4-5302-aae1-1e57efe5e5d2`: (Hardware support for relocation and limit registers) According to size of partitions, the multiple partition schemes are divided into two types: i. Multiple fixed partition/ multiprogramming with fixed task(MFT) ii. Multiple variable partition/ multiprogramming with variable task(MVT) i. Multiple fixed partitions: Main memory is divided into a number of static partitions at system generation time. In this case, any process whose size is less than or equal to the partition size can be loaded int
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_mft_mvt__q_english | english | What is the difference between multiple fixed partitions (MFT) and multiple variable partitions (MVT)? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_mft_mvt__q_hindi | hindi | एकाधिक स्थिर विभाजन (MFT) और एकाधिक परिवर्तनीय विभाजन (MVT) में क्या अंतर है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_mft_mvt__q_hinglish | hinglish | MFT aur MVT partitioning mein kya difference hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_producer_consumer

- **Domain:** operating systems
- **Subject:** process synchronization
- **Source language:** english
- **Source type:** pdf
- **Query type:** conceptual
- **Difficulty:** easy
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa90e314ac03b89c7624ccb`
- **Relevant chunk_id(s):** `f3c769b8-86c7-5928-aadc-9464f1113f6e`
- **Reviewer notes (from Claude):** Chunk defines the producer-consumer paradigm and the bounded/unbounded buffer setup.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `f3c769b8-86c7-5928-aadc-9464f1113f6e`: Lecture # 17 Process Synchronization A situation where several processes access and manipulate the same data concurrently and the outcome of the execution depends on the particular order in which the access takes place, is called a race condition. Producer-Consumer Problem Paradigm for cooperating processes, producer process produces information that is consumed by a consumer process. To allow producer and consumer processes to run concurrently, we must have available a buffer of items that can 
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_producer_consumer__q_english | english | What is the producer-consumer problem in process synchronization? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_producer_consumer__q_hindi | hindi | प्रोसेस सिंक्रोनाइजेशन में प्रोड्यूसर-कंज्यूमर समस्या क्या है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_producer_consumer__q_hinglish | hinglish | Process synchronization mein producer-consumer problem kya hoti hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_process_vs_program

- **Domain:** operating systems
- **Subject:** process management
- **Source language:** english
- **Source type:** pdf
- **Query type:** comparison
- **Difficulty:** easy
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa72e4416cbab6b27d5f50b`
- **Relevant chunk_id(s):** `8bde1fee-6475-5709-b3d3-df7cc009e665`
- **Reviewer notes (from Claude):** Chunk contains an explicit numbered list contrasting process vs program (static vs dynamic, secondary vs main storage, active vs passive entity, etc.).

**Actual supporting excerpt(s) (first ~500 chars each):**

> `8bde1fee-6475-5709-b3d3-df7cc009e665`: Lecture #6(UNIT-II) Process Concept  Informally, a process is a program in execution. A process is more than the program code, which is sometimes known as the text section. It also includes the current activity, as represented by the value of the program counter and the contents of the processor's registers. In addition, a process generally includes the process stack, which contains temporary data (such as method parameters, return addresses, and local variables), and a data section, which cont
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_process_vs_program__q_english | english | What is the difference between a process and a program? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_process_vs_program__q_hindi | hindi | प्रोसेस और प्रोग्राम में क्या अंतर है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_process_vs_program__q_hinglish | hinglish | Process aur program mein kya farak hota hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_semaphore_wait_signal

- **Domain:** operating systems
- **Subject:** process synchronization
- **Source language:** english
- **Source type:** pdf
- **Query type:** factual
- **Difficulty:** easy
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa846698a7bd709c53a5f4e`
- **Relevant chunk_id(s):** `ccda131d-5398-57b1-87ea-a90e73ae79ea`
- **Reviewer notes (from Claude):** Chunk gives the classical pseudocode definitions of wait(S) and signal(S) and states they must execute indivisibly.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `ccda131d-5398-57b1-87ea-a90e73ae79ea`: Lecture # 20 Semaphores The solutions to the critical-section problem presented before are not easy to generalize to more complex problems. To overcome this difficulty, we can use a synchronization tool called a semaphore. A semaphore S is an integer variable that, apart from initialization, is accessed only through two standard atomic operations: wait and signal. These operations were originally termed P (for wait; from the Dutch proberen, to test) and V (for signal; from verhogen, to increment
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_semaphore_wait_signal__q_english | english | What are the wait and signal operations on a semaphore? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_semaphore_wait_signal__q_hindi | hindi | सेमाफोर पर वेट और सिग्नल ऑपरेशन क्या होते हैं? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_semaphore_wait_signal__q_hinglish | hinglish | Semaphore ke wait aur signal operations kya hote hain? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_user_level_threads

- **Domain:** operating systems
- **Subject:** threads
- **Source language:** english
- **Source type:** pdf
- **Query type:** advantage_disadvantage
- **Difficulty:** medium
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa72e4416cbab6b27d5f50b`
- **Relevant chunk_id(s):** `0a3a084e-013e-569e-bb20-08a65f2f05a6`
- **Reviewer notes (from Claude):** Chunk lists user-level thread advantages (no OS modification needed, simple representation/management, fast switching) and disadvantages.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `0a3a084e-013e-569e-bb20-08a65f2f05a6`: 2. Resource sharing: By default, threads share the memory and the resources of the process to which they belong. The benefit of code sharing is that it allows an application to have several different threads of activity all within the same address space. 3. Economy: Allocating memory and resources for process creation is costly. Alternatively, because threads share resources of the process to which they belong, it is more economical to create and context switch threads. It can be difficult to ga
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_user_level_threads__q_english | english | What are the advantages of user-level threads? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_user_level_threads__q_hindi | hindi | यूज़र-लेवल थ्रेड्स के क्या फायदे हैं? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_user_level_threads__q_hinglish | hinglish | User-level threads ke kya advantages hote hain? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_sjf_difficulty

- **Domain:** operating systems
- **Subject:** cpu scheduling
- **Source language:** english
- **Source type:** pdf
- **Query type:** cause_reason
- **Difficulty:** medium
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa72dae16cbab6b27d5f508`
- **Relevant chunk_id(s):** `ae88f902-a448-573d-a7ea-a7ea2b4191f5`
- **Reviewer notes (from Claude):** *(Reworded in Phase 3.1)* Chunk states there is no way to know the length of the next CPU burst at the short-term scheduling level, which makes SJF DIFFICULT to implement directly in practice (it can only be approximated) -- not that it is mathematically impossible.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `ae88f902-a448-573d-a7ea-a7ea2b4191f5`: the minimum average waiting time for a given set of processes. By moving a short process before a long one, the waiting time of the short process decreases more than it increases the waiting time of the long process. Consequently, the average waiting time decreases. The real difficulty with the SJF algorithm is knowing the length of the next CPU request. For long-term (or job) scheduling in a batch system, we can use as the length the process time limit that a user specifies when he submits the 
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_sjf_difficulty__q_english | english | *(Phase 3.1: reworded from an absolute "can't be implemented" claim to a "difficult in practice" claim)* Why is the Shortest Job First (SJF) algorithm difficult to implement in practice for short-term CPU scheduling? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sjf_difficulty__q_hindi | hindi | शॉर्ट-टर्म CPU शेड्यूलिंग के लिए शॉर्टेस्ट जॉब फर्स्ट (SJF) एल्गोरिदम को व्यवहार में लागू करना कठिन क्यों है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sjf_difficulty__q_hinglish | hinglish | Short-term CPU scheduling ke liye SJF algorithm ko practically implement karna mushkil kyu hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_ipc_direct_vs_indirect

- **Domain:** operating systems
- **Subject:** inter-process communication
- **Source language:** english
- **Source type:** pdf
- **Query type:** comparison
- **Difficulty:** medium
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa72dae16cbab6b27d5f508`
- **Relevant chunk_id(s):** `13c21374-754e-5a0c-88d6-f6df04cb2370`
- **Reviewer notes (from Claude):** Chunk contrasts direct communication (send(P,message)/receive(Q,message), naming processes explicitly) with indirect communication via shared mailboxes.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `13c21374-754e-5a0c-88d6-f6df04cb2370`: Lecture #15 Inter-process Communication (IPC)  Mechanism for processes to communicate and to synchronize their actions.  Message system – processes communicate with each other without resorting to shared variables.  IPC facility provides two operations: 1. send(message) – message size fixed or variable 2. receive(message)  If P and Q wish to communicate, they need to: 1. establish a communication link between them 2. exchange messages via send/receive  Implementation of communication link 1
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_ipc_direct_vs_indirect__q_english | english | What is the difference between direct and indirect communication in inter-process communication (IPC)? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_ipc_direct_vs_indirect__q_hindi | hindi | इंटर-प्रोसेस कम्युनिकेशन (IPC) में डायरेक्ट और इनडायरेक्ट कम्युनिकेशन में क्या अंतर है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_ipc_direct_vs_indirect__q_hinglish | hinglish | IPC mein direct aur indirect communication mein kya difference hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_lru_page_replacement

- **Domain:** operating systems
- **Subject:** memory management
- **Source language:** english
- **Source type:** pdf
- **Query type:** explanation
- **Difficulty:** medium
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa72dae16cbab6b27d5f508`
- **Relevant chunk_id(s):** `d372f4f7-85f8-5f73-b66a-5e71af9251ff`
- **Reviewer notes (from Claude):** Chunk explains LRU replaces the page that has not been used for the longest period of time, and describes counter-based and stack-based implementations.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `d372f4f7-85f8-5f73-b66a-5e71af9251ff`: It is simply “Replace the page that will not be used for the longest period of time”. Use of this page-replacement algorithm guarantees the lowest possible pagefault rate for a fixed number of frames. Example: (Optimal page-replacement algorithm) 3. LRU Page Replacement algorithm If we use the recent past as an approximation of the near future, then we will replace the page that has not been used for the longest period of time. This approach is the least- recently-used (LRU) algorithm. LRU repla
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_lru_page_replacement__q_english | english | How does the LRU (Least Recently Used) page replacement algorithm decide which page to replace? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_lru_page_replacement__q_hindi | hindi | LRU (लीस्ट रीसेंटली यूज्ड) पेज रिप्लेसमेंट एल्गोरिदम यह कैसे तय करता है कि कौन सा पेज बदला जाए? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_lru_page_replacement__q_hinglish | hinglish | LRU page replacement algorithm ye kaise decide karta hai ki kaunsa page replace karna hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_os_modules

- **Domain:** operating systems
- **Subject:** os architecture
- **Source language:** hindi
- **Source type:** youtube
- **Query type:** conceptual
- **Difficulty:** easy
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `f404ac22-88f5-591d-b20f-e0502be6ef96`
- **Reviewer notes (from Claude):** Government-ministries analogy; states OS has separate modules per function and singles out process management and memory management as the two modules emphasized in this course.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `f404ac22-88f5-591d-b20f-e0502be6ef96`: नम े ं ट ऑफ इ ं ड ि य ा क ा ग ो ल ह ै म ा न ल ी ज ि ए सबक ा स ा थ सबक ा व ि क ा स । व ो क ै स े ह ो ग ा? 58 मिनिस्ट्रीज हैं। 93 डिपार्टमेंट्स हैं जो डायरेक्ट गवर्नमेंट ऑफ इंडिया को रिपोर्ट करते हैं। हम कह रहे हैं अगर सारे डिपार्टमेंट अच्छे से काम करेंगे तो काम भी ठीक से होगा। ठीक उसी तरह यहां पर भी ऑपरेटिंग सिस्टम में फाइल मैनेजमेंट, प्रोसेस मैनेजमेंट, इनपुट आउटपुट डिवाइस, नेटवर्क, स्टोरेज, सिक्योरिटी हर काम को करने के लिए अलग मॉड्यूल हैं। और अगर ये सारे मॉड्यूल्स फंक्शन सही से काम करेंगे तो ओवर
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_os_modules__q_english | english | Why does an operating system have separate modules for tasks like file management, process management, and networking? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_os_modules__q_hindi | hindi | ऑपरेटिंग सिस्टम में फाइल मैनेजमेंट, प्रोसेस मैनेजमेंट और नेटवर्किंग जैसे कार्यों के लिए अलग-अलग मॉड्यूल क्यों होते हैं? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_os_modules__q_hinglish | hinglish | Operating system mein file management, process management aur networking ke liye alag-alag modules kyu hote hain? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_real_time_os

- **Domain:** operating systems
- **Subject:** os types
- **Source language:** hindi
- **Source type:** youtube
- **Query type:** factual
- **Difficulty:** easy
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `280c2744-c8bb-5f78-854b-52e3b77c8613`
- **Reviewer notes (from Claude):** Air-traffic-control example used to define a real-time OS as one that must guarantee task completion within a fixed time constraint.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `280c2744-c8bb-5f78-854b-52e3b77c8613`: एयरक्राफ्ट का या मान लीजिए एग्जांपल है एटीसी का। है ना? किसी भी समय इंडियन एयर स्पेस के अंदर मान लीजिए देयर आर थाउजेंड्स ऑफ़ एयरक्राफ्ट। मान के लीजिए रियलिटी है भाई थाउजेंड्स ऑफ़ एयरक्राफ्ट होते हैं। तो क्या हमारा सिस्टम हैंग हो सकता है? या अगर कोई एयरक्राफ्ट हमसे रिसोंड करने के लिए बोल रहा है क्या उसमें लैग हो सकता है? उसमें लैग नहीं हो सकता। तो ये कुछ एग्जांपल ऐसे हैं कि सर काम सिर्फ करना नहीं है। गारंटी के साथ इतने फिक्स टाइम कांस्टेंट के अंदर करना है। तो अगर इस तरह की कंडीशन हमारे ऊपर होती है 
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_real_time_os__q_english | english | What is a real-time operating system? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_real_time_os__q_hindi | hindi | रियल टाइम ऑपरेटिंग सिस्टम क्या होता है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_real_time_os__q_hinglish | hinglish | Real time operating system kya hota hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_process_stack_contents

- **Domain:** operating systems
- **Subject:** process management
- **Source language:** hindi
- **Source type:** youtube
- **Query type:** factual
- **Difficulty:** medium
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `15197ab2-7fc0-5cc8-9860-5c0409be66ba`
- **Reviewer notes (from Claude):** States data section = global variables, heap = runtime dynamic allocation, stack (activation record) = parameters/return addresses/local variables. Same underlying concept as c_process_vs_program's English PDF chunk, kept separate -- see also c_process_memory_cross_document_hard below.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `15197ab2-7fc0-5cc8-9860-5c0409be66ba`: का जितना कोड है वो पूरा कोड है। पीसीबी इससे अलग है। है ना? मैं मेमोरी में आपको प्रोसेस किस तरह से दिखेगा उसकी इमेज दिखा रहा हूं। देन उसके ऊपर आपको मिलेगा डेटा सेक्शन जहां पे ग्लोबल वेरिएबल्स जो है हमारे हैं वो डिक्लेअर होते हैं। उससे ऊपर आपको मिलेगा हीप जहां पे रन टाइम पे अगर डायनेमिक मेमोरी एलोकेशन हम करते हैं तो वो हिप में होता है और जो हमारा पूरा एक्टिवेशन रिकॉर्ड है स्टक वो ऊपर से नीचे चलता है जिसमें पैराटर्स रिटर्न्स वेरिएबल एड्रेसेस वो सारी इनेशन रहती है। अगेन बहुत डिटेल में जाने की जरूरत 
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_process_stack_contents__q_english | english | What does the stack section of a process contain? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_process_stack_contents__q_hindi | hindi | एक प्रोसेस के स्टैक सेक्शन में क्या होता है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_process_stack_contents__q_hinglish | hinglish | Process ke stack section mein kya hota hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_sjf_not_implementable

- **Domain:** operating systems
- **Subject:** cpu scheduling
- **Source language:** hindi
- **Source type:** youtube
- **Query type:** cause_reason
- **Difficulty:** medium
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `b15a9c9f-c3c6-54ee-a865-5b328b74f755`
- **Reviewer notes (from Claude):** States SJF is not implementable because a process's own CPU burst time is not known in advance, and is used only as a theoretical reference point. Same underlying concept as c_sjf_difficulty's English PDF chunk, kept separate -- see also c_sjf_cross_document_hard below.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `b15a9c9f-c3c6-54ee-a865-5b328b74f755`: ह ै । थ ् य ो र ि ट ि कल आईड ि य ा ह ै । आप ब ो ल े ं ग े इ ं प ् ल ी म े ं ट े बल क ् य ो ं नह ी ं ह ै? भाई सोचो पूरा का पूरा जो एल्गोरिदम है वो इस बात पे टिका हुआ है कि किसका बस टाइम क्या है? लेकिन सवाल ये है जब प्रोसेस एग्जीक्यूशन के लिए आता है क्या प्रोसेस को पहले से पता होता है मेरा बस टाइम क्या है क्या प्रोसेस को पता है कि वो ओवरऑल CPU पे कितने समय के लिए एग्जीक्यूट करेगा ऑब्वियसली नहीं पता होता नहीं पता होता ना सो दैट इज़ अ प्रॉब्लम तो ये ओवरऑल एल्गोरिदम अच्छा है बट क्योंकि बस टाइम हमें नह
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_sjf_not_implementable__q_english | english | Why is the Shortest Job First (SJF) scheduling algorithm difficult to implement in practice? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sjf_not_implementable__q_hindi | hindi | शॉर्टेस्ट जॉब फर्स्ट (SJF) शेड्यूलिंग एल्गोरिदम को व्यवहार में लागू करना कठिन क्यों है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sjf_not_implementable__q_hinglish | hinglish | SJF scheduling algorithm ko practically implement karna mushkil kyu hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_page_fault_definition

- **Domain:** operating systems
- **Subject:** memory management
- **Source language:** hindi
- **Source type:** youtube
- **Query type:** factual
- **Difficulty:** easy
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `de102609-87b3-5d1d-b5d6-78591df889cd`
- **Reviewer notes (from Claude):** Explains the valid/invalid bit in the page table and defines a page fault as referencing a page whose bit is invalid (not currently in main memory).

**Actual supporting excerpt(s) (first ~500 chars each):**

> `de102609-87b3-5d1d-b5d6-78591df889cd`: म े र ा क ौ न स ा प े ज अभ ी म े न म े म ो र ी म े ं क ौ न स ा नह ी ं ह ै । त ो हम क ् य ा करत े ह ै ं? पेज टेबल के अंदर ही एक एडिशनल बिट लगा देते हैं जिसे बोलते हैं वैलिड इनवैलिड बिट। तो जहां-जहां वैलिड बिट की वैल्यू लेट मी से वैलिड है। लेट मी से वन है वहां मान लेते हैं कि ये पेज अभी है। और अगर इनवैलिड है तो मानना पड़ेगा कि वो पेज अभी मेन मेमोरी में नहीं है। अगर हम किसी ऐसे पेज को रेफर कर लेते हैं। सीपीयू ने बोला मेरे को वो पेज चाहिए जो अभी नहीं है। इस सिनेरियो को बोलते है पेज फ़ौल्ट। क्या हो गय
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_page_fault_definition__q_english | english | What is a page fault? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_page_fault_definition__q_hindi | hindi | पेज फॉल्ट क्या होता है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_page_fault_definition__q_hinglish | hinglish | Page fault kya hota hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_fcfs_disk_scheduling

- **Domain:** operating systems
- **Subject:** disk scheduling
- **Source language:** hindi
- **Source type:** youtube
- **Query type:** explanation
- **Difficulty:** medium
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `7d131130-e14e-597a-9cb1-f3dc5dad183e`
- **Reviewer notes (from Claude):** Explains FCFS serves disk requests strictly in arrival order regardless of track position, causing more physical head movement than necessary.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `7d131130-e14e-597a-9cb1-f3dc5dad183e`: टल आईड ि य ा ह ो सकत ा ह ै द ै ट इज़ एफस ी एफएस ज ो हर जगह हम य ू ज़ करत े आए ह ै ं । त ो एफस ी एफएस क ् य ा ब ो ल े ग ा सर? वो यह बोलेगा कि फॉर एग्जांपल अगर यह हमारे पास सारे ट्रैक नंबर हैं तो मैं जैसे यहां शायद दिख भी रहा है। मेरे को फर्क नहीं पड़ता कि आपका कौन सा ट्रैक नंबर आगे है, कौन सा पीछे है या मुझे फिजिकली कितना मूव करना पड़ेगा। जो रिक्वेस्ट पहले आई थी उसको हम पहले आंसर करेंगे। जो बाद में आई थी उसको बाद में आंसर करेंगे। अब ये है तो वैलिड कोई प्रॉब्लम नहीं है इसमें। बट जैसा आप देख रहे हैं 
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_fcfs_disk_scheduling__q_english | english | What is a drawback of the FCFS disk scheduling algorithm? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_fcfs_disk_scheduling__q_hindi | hindi | FCFS डिस्क शेड्यूलिंग एल्गोरिदम की एक कमी क्या है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_fcfs_disk_scheduling__q_hinglish | hinglish | FCFS disk scheduling algorithm ka ek drawback kya hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_memory_hierarchy_locality

- **Domain:** operating systems
- **Subject:** memory management
- **Source language:** hindi
- **Source type:** youtube
- **Query type:** explanation
- **Difficulty:** medium
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `2c1abf3a-9337-5167-8b7c-e6fb816f20cc`, `1e2576b8-b408-5ded-9144-2d977076f961`
- **Reviewer notes (from Claude):** Discusses cache-miss fallback to secondary/virtual memory, gives concrete size-ratio numbers (e.g. main memory ~64x smaller than secondary), introduces the term 'locality of reference', and (via the second chunk) explains it with a showroom/godown/factory analogy naming both temporal and spatial locality.
- **✅ PHASE 3.1 FINAL CORRECTION: `review_flag: RE_VERIFIED_SUFFICIENT`** *(was `NEEDS_ADJACENT_CHUNK_VERIFICATION`)*. Qdrant is now reachable. Live scroll of document `6aaa7e8c81e2b76728b76bb6` sorted by `start_timestamp` located the real continuation chunk `1e2576b8-b408-5ded-9144-2d977076f961` (same start_timestamp, 3966.0) immediately following `2c1abf3a...`. Its text opens by repeating the exact cut-off line ("...तो इतने छोटे सिस्टम से कैसे चीजें मैनेज हो जाती हैं?") and then fully explains locality of reference with a showroom/godown/factory analogy, explicitly naming both temporal and spatial locality. Added to `relevant_chunk_ids`. A third chunk sharing the same start_timestamp, `29d10e3f-8811-5937-999e-db01f7019a02`, was inspected and confirmed to be an unrelated topic (variable-size memory partitioning, restaurant-table analogy) -- deliberately **not** added.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `2c1abf3a-9337-5167-8b7c-e6fb816f20cc`: प्राइमरी मेमोरी अलग-अलग नाम जिनसे हम सब बुलाते हैं। अगर कैश में नहीं मिलता तो उधर जाते हैं। एंड वर्स्ट स्कैन सिनेरियो अगर उधर भी नहीं मिलता तो देखो CPU डायरेक्ट इधर नहीं जाता। हम सेकेंडरी मेमोरी या लॉजिकल मेमोरी या वर्चुअल मेमोरी या ऑिलरी मेमोरी सर्च करते हैं और डेटा को इधर लोड करते हैं। तो दैट इज़ द एंटायर आईडिया जिस तरह से हम काम करते हैं। ये वही एग्जांपल मैं समझाता हूं। अच्छा अब एक इंपॉर्टेंट बात ये है लोकालिटी ऑफ़ रेफरेंस। बड़ी इंपॉर्टेंट बात है समझने के लिए। आमतौर पे जैसे मान लीजिए सेकेंडरी मे
>
> `1e2576b8-b408-5ded-9144-2d977076f961` *(added in the Phase 3.1 final correction)*: 64 टाइम छोटा हो। तो इतने छोटे सिस्टम से कैसे चीजें मैनेज हो जाती हैं? तो मैं बोलता हूं वही लोकालिटी ऑफ़ रेफरेंस वाली बात है। जैसे शोरूम में बहुत लिमिटेड कार होती है। अगर आप किसी कंपनी के गोडाउन में जाएंगे... और फैक्ट्री में जाएंगे तो हो सकता है वहां तो हजारों लाखों गाड़ियां हो सकती हैं। तो आर्गुमेंट ये है लोकालिटी ऑफ़ रेफरेंस ये कहता है कि जैसे-जैसे चीजें यूज़ होती जाती है, हमें आईडिया होता जाता है कि कौन सा डेटा इंपॉर्टेंट है... टेंपोरल लोकालिटी हो सकती है... स्पेशल लोकालिटी हो सकती है...
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_memory_hierarchy_locality__q_english | english | What is locality of reference in the context of memory hierarchy? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_memory_hierarchy_locality__q_hindi | hindi | मेमोरी हायरार्की के संदर्भ में लोकैलिटी ऑफ रेफरेंस क्या है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_memory_hierarchy_locality__q_hinglish | hinglish | Memory hierarchy ke context mein locality of reference kya hoti hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_hold_and_wait_deadlock

- **Domain:** operating systems
- **Subject:** deadlocks
- **Source language:** hindi
- **Source type:** youtube
- **Query type:** cause_reason
- **Difficulty:** medium
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `d487a846-1937-5a17-a6f6-f0fe58575fca`
- **Reviewer notes (from Claude):** Explains the informal hold-and-wait scenario: a process holds an acquired resource while waiting for another, and if every process behaves this way, deadlock results.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `d487a846-1937-5a17-a6f6-f0fe58575fca`: ो ग े त ो ह ो सकत ा ह ै ब ा द म े ं प ् ल े ट भ ी न ा म ि ल े । त ो य ू ज ु अल ी हम क ् य ा कर े ं ग े? जो रिसोर्स मिल रहा है उसको होल्ड करके रख लेंगे। फिर दूसरे रिसोर्स के लिए वेट करेंगे। और यूजुअली हर प्रोसेस का यही नेचर होता है। तो अगर हर कोई ऐसा सोचता है तो डेड लॉक लगे। अगर लोग समझदार हो जाए कि नहीं नहीं सर जब तक दोनों नहीं मिलेंगे हम होल्ड नहीं करेंगे तो डेड लॉक नहीं लगेगा।
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_hold_and_wait_deadlock__q_english | english | How does holding a resource while waiting for another cause a deadlock? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_hold_and_wait_deadlock__q_hindi | hindi | एक रिसोर्स को पकड़े रखते हुए दूसरे के लिए इंतज़ार करना डेडलॉक का कारण कैसे बनता है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_hold_and_wait_deadlock__q_hinglish | hinglish | Ek resource ko hold karke rakhna aur dusre resource ka wait karna deadlock ka reason kaise banta hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_sql_null

- **Domain:** database management systems
- **Subject:** sql
- **Source language:** english
- **Source type:** pdf
- **Query type:** explanation
- **Difficulty:** medium
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Relevant chunk_id(s):** `b1766d23-6160-5557-82a0-6e03804af525`
- **Reviewer notes (from Claude):** Chunk explains three-valued logic (true/false/unknown) for comparisons and boolean connectives involving NULL, and the IS NULL / IS NOT NULL operators.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `b1766d23-6160-5557-82a0-6e03804af525`: SQL provides a special column value called null to use in such situations. We use null when the column value is either unknown or inapplicable. Using our Sailor table definition, we might enter the row 〈98, Dan, null, 39〉 to represent Dan. The presence of null values complicates many issues, and we consider the impact of null values on SQL in this section. Comparisons Using Null Values Consider a comparison such as rating = 8. If this is applied to the row for Dan, is this condition true or fals
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_sql_null__q_english | english | How does SQL evaluate comparisons involving NULL values? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sql_null__q_hindi | hindi | SQL में NULL वैल्यू वाले तुलनात्मक एक्सप्रेशन का मूल्यांकन कैसे होता है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sql_null__q_hinglish | hinglish | SQL mein NULL value wale comparisons ka result kya hota hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_sql_transaction_end

- **Domain:** database management systems
- **Subject:** transactions
- **Source language:** english
- **Source type:** pdf
- **Query type:** factual
- **Difficulty:** easy
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Relevant chunk_id(s):** `581137a9-893e-58a0-9137-43c8cd89d235`
- **Reviewer notes (from Claude):** Chunk states a transaction ends via COMMIT WORK or ROLLBACK WORK, and that statements implicitly commit unless autocommit is disabled.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `581137a9-893e-58a0-9137-43c8cd89d235`: Transaction Definition in SQL  Data manipulation language must include a construct for specifying the set of actions that comprise a transaction.  In SQL, a transaction begins implicitly.  A transaction in SQL ends by: Commit work commits current transaction and begins a new one. Rollback work causes current transaction to abort.  In almost all database systems, by default, every SQL statement also commits implicitly if it executes successfully Implicit commit can be turned off by a datab
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_sql_transaction_end__q_english | english | How does a transaction end in SQL? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sql_transaction_end__q_hindi | hindi | SQL में एक ट्रांजैक्शन कैसे समाप्त होता है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sql_transaction_end__q_hinglish | hinglish | SQL mein transaction kaise end hota hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_transaction_manager_role

- **Domain:** database management systems
- **Subject:** dbms architecture
- **Source language:** english
- **Source type:** pdf
- **Query type:** factual
- **Difficulty:** easy
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Relevant chunk_id(s):** `97a78d80-630a-5912-a47d-b606ef7f06fc`
- **Reviewer notes (from Claude):** Chunk states the transaction manager ensures the database remains consistent despite system/transaction failures and that concurrent executions don't conflict.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `97a78d80-630a-5912-a47d-b606ef7f06fc`: 18 · Authorization and integrity manager, which tests for the satisfaction of integrity constraints and checks the authority of users to access data. · Transaction manager, which ensures that the database remains in a consistent (correct) state despite system failures, and that concurrent transaction executions proceed without conflicting. · File manager, which manages the allocation of space on disk storage and the data structures used to represent information stored on disk. · Buffer manager, 
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_transaction_manager_role__q_english | english | What is the role of the transaction manager in a database system? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_transaction_manager_role__q_hindi | hindi | डेटाबेस सिस्टम में ट्रांजैक्शन मैनेजर की भूमिका क्या है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_transaction_manager_role__q_hinglish | hinglish | Database system mein transaction manager ka role kya hota hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_relational_join

- **Domain:** database management systems
- **Subject:** relational algebra
- **Source language:** english
- **Source type:** pdf
- **Query type:** conceptual
- **Difficulty:** medium
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Relevant chunk_id(s):** `11dd0510-55ca-592d-8c90-89a1600eb565`
- **Reviewer notes (from Claude):** Chunk gives the formal condition-join definition R join_c S = selection_c(R x S), a cross-product followed by a selection.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `11dd0510-55ca-592d-8c90-89a1600eb565`: Joins The join operation is one of the most useful operations in relational algebra and is the most commonly used way to combine information from two or more relations. Although a join can be defined as a cross-product followed by selections and projections, joins arise much more frequently in practice than plain cross-products. joins have received a lot of attention, and there are several variants of the join operation. Condition Joins The most general version of the join operation accepts a jo
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_relational_join__q_english | english | How is the join operation defined in relational algebra? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_relational_join__q_hindi | hindi | रिलेशनल अलजेब्रा में जॉइन ऑपरेशन को कैसे परिभाषित किया जाता है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_relational_join__q_hinglish | hinglish | Relational algebra mein join operation ko kaise define kiya jata hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_sql_query_evaluation_steps

- **Domain:** database management systems
- **Subject:** sql
- **Source language:** english
- **Source type:** pdf
- **Query type:** explanation
- **Difficulty:** medium
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Relevant chunk_id(s):** `9f59b5fd-98d8-595f-9be6-fbc47b2725db`
- **Reviewer notes (from Claude):** Chunk lists the four conceptual steps: cross-product of FROM tables, filter by WHERE, project SELECT columns, then DISTINCT if specified.
- **✅ PHASE 3.1: `review_flag: RE_VERIFIED_SUFFICIENT`.** Re-checked against the COMPLETE chunk text (not just the excerpt): all four steps -- "Compute the cross-product of the tables in the from-list", "Delete those rows... that fail the qualification conditions", "Delete all columns that do not appear in the select-list", "If DISTINCT is specified, eliminate duplicate rows" -- are explicitly present verbatim. No change needed.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `9f59b5fd-98d8-595f-9be6-fbc47b2725db`: SELECT S. sid, S. sname, S. rating, S. age FROM Sailors AS S WHERE S. rating > 7 We now consider the syntax of a basic SQL query in more detail.  The from-list in the FROM clause is a list of table names. A table name can be followed by a range variable; a range variable is particularly useful when the same table name appears more than once in the from-list.  The select-list is a list of (expressions involving) column names of tables named in the from-list. Column names can be prefixed by a ra
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_sql_query_evaluation_steps__q_english | english | What are the conceptual evaluation steps for a basic SQL query? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sql_query_evaluation_steps__q_hindi | hindi | एक बेसिक SQL क्वेरी के लिए कॉन्सेप्चुअल मूल्यांकन चरण क्या हैं? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_sql_query_evaluation_steps__q_hinglish | hinglish | Basic SQL query ke conceptual evaluation steps kya hote hain? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_transaction_isolation_levels

- **Domain:** database management systems
- **Subject:** concurrency control
- **Source language:** english
- **Source type:** pdf
- **Query type:** comparison
- **Difficulty:** medium
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Relevant chunk_id(s):** `04d1ab4b-8edd-5290-b5d7-7261aa5f1c5e`
- **Reviewer notes (from Claude):** Chunk lists READ UNCOMMITTED / READ COMMITTED / REPEATABLE READ / SERIALIZABLE and their dirty-read/unrepeatable-read/phantom exposure.
- **✅ PHASE 3.1: `review_flag: RE_VERIFIED_SUFFICIENT`.** Re-checked against the COMPLETE chunk text (not just the excerpt): all four isolation levels AND the full dirty-read/unrepeatable-read/phantom table ("READ UNCOMMITTED Maybe Maybe Maybe / READ COMMITTED No Maybe Maybe / REPEATABLE READ No No Maybe / SERIALIZABLE No No No") are explicitly present. No change needed.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `04d1ab4b-8edd-5290-b5d7-7261aa5f1c5e`: Transaction Characteristics -Prepared by M V Kamal, Associate Professor, CSE Dept Every transaction has three characteristics: access mode, diagnostics size, and isolation level. The diagnostics size determines the number of error conditions that can be recorded. If the access mode is READ ONLY, the transaction is not allowed to modify the database. Thus, INSERT, DELETE, UPDATE, and CREATE commands cannot be executed. If we have to execute one of these commands, the access mode should be set to 
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_transaction_isolation_levels__q_english | english | What are the different transaction isolation levels in SQL, and how do they differ? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_transaction_isolation_levels__q_hindi | hindi | SQL में विभिन्न ट्रांजैक्शन आइसोलेशन लेवल क्या हैं, और वे एक-दूसरे से कैसे अलग हैं? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_transaction_isolation_levels__q_hinglish | hinglish | SQL mein different transaction isolation levels kya hote hain, aur ye ek dusre se kaise alag hain? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_decomposition_redundancy

- **Domain:** database management systems
- **Subject:** schema design
- **Source language:** english
- **Source type:** pdf
- **Query type:** cause_reason
- **Difficulty:** medium
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Relevant chunk_id(s):** `0f600426-b53c-5002-b897-e1564f6688dc`
- **Reviewer notes (from Claude):** Chunk explains redundancy from an unnatural attribute association can be fixed by decomposing into smaller relations, with a worked Hourly_Emps/Wages example.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `0f600426-b53c-5002-b897-e1564f6688dc`: 15. 1. 2 Use of Decompositions Intuitively, redundancy arises when a relational schema forces an association between attributes that is not natural. Functional dependencies (and, for that matter, other ICs) can be used to identify such situations and to suggest refinements to the schema. The essential idea is that many problems arising from redundancy can be addressed by replacing a relation with a collection of `smaller' relations. Each of the smaller relations contains a (strict) subset of the
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_decomposition_redundancy__q_english | english | Why would a database designer decompose a relation into smaller relations? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_decomposition_redundancy__q_hindi | hindi | एक डेटाबेस डिज़ाइनर एक रिलेशन को छोटे रिलेशनों में क्यों विभाजित करेगा? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_decomposition_redundancy__q_hinglish | hinglish | Database designer ek relation ko chhote relations mein kyu decompose karega? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_schema_vs_instance

- **Domain:** database management systems
- **Subject:** database fundamentals
- **Source language:** english
- **Source type:** pdf
- **Query type:** comparison
- **Difficulty:** easy
- **Workspace ID:** `6a8de2d7e43679cbe2ee243d`
- **Document ID:** `6aa8457c8a7bd709c53a5f46`
- **Relevant chunk_id(s):** `bdf57cce-bdec-5276-a29e-e7898de07418`
- **Reviewer notes (from Claude):** Chunk states schema corresponds to a type definition (does not change), while an instance corresponds to a variable's value (changes over time).

**Actual supporting excerpt(s) (first ~500 chars each):**

> `bdf57cce-bdec-5276-a29e-e7898de07418`: 27 instant in time. The concept of a relation corresponds to the programming-language notion of a variable, while the concept of a relation schema corresponds to the programming-language notion of type definition. In general, a relation schema consists of a list of attributes and their corresponding domains. The concept of a relation instance corresponds to the programming-language notion of a value of a variable. The value of a given variable may change with time; Figure 1. 9: The department re
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_schema_vs_instance__q_english | english | What is the difference between a relation schema and a relation instance? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_schema_vs_instance__q_hindi | hindi | रिलेशन स्कीमा और रिलेशन इंस्टेंस में क्या अंतर है? | ☐ approved / ☐ rejected / ☐ needs edit |
| c_schema_vs_instance__q_hinglish | hinglish | Relation schema aur relation instance mein kya difference hai? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_sjf_cross_document_hard

- **Domain:** operating systems
- **Subject:** cpu scheduling
- **Source language:** mixed
- **Source type:** mixed
- **Query type:** multi_document
- **Difficulty:** hard
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa72dae16cbab6b27d5f508`
- **All contributing document_ids:** `6aa72dae16cbab6b27d5f508`, `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `ae88f902-a448-573d-a7ea-a7ea2b4191f5`, `b15a9c9f-c3c6-54ee-a865-5b328b74f755`
- **Reviewer notes (from Claude):** The same underlying reason (a process's own future CPU burst time is not knowable in advance) is independently explained in the English PDF (c_sjf_difficulty) and the Hindi YouTube lecture (c_sjf_not_implementable) -- two different documents, two different source languages, one workspace. A workspace-aware retriever should be able to surface either or both pieces of evidence for this broader phrasing of the question, not just whichever single document happens to match keywords best.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `ae88f902-a448-573d-a7ea-a7ea2b4191f5`: the minimum average waiting time for a given set of processes. By moving a short process before a long one, the waiting time of the short process decreases more than it increases the waiting time of the long process. Consequently, the average waiting time decreases. The real difficulty with the SJF algorithm is knowing the length of the next CPU request. For long-term (or job) scheduling in a batch system, we can use as the length the process time limit that a user specifies when he submits the 
>
> `b15a9c9f-c3c6-54ee-a865-5b328b74f755`: ह ै । थ ् य ो र ि ट ि कल आईड ि य ा ह ै । आप ब ो ल े ं ग े इ ं प ् ल ी म े ं ट े बल क ् य ो ं नह ी ं ह ै? भाई सोचो पूरा का पूरा जो एल्गोरिदम है वो इस बात पे टिका हुआ है कि किसका बस टाइम क्या है? लेकिन सवाल ये है जब प्रोसेस एग्जीक्यूशन के लिए आता है क्या प्रोसेस को पहले से पता होता है मेरा बस टाइम क्या है क्या प्रोसेस को पता है कि वो ओवरऑल CPU पे कितने समय के लिए एग्जीक्यूट करेगा ऑब्वियसली नहीं पता होता नहीं पता होता ना सो दैट इज़ अ प्रॉब्लम तो ये ओवरऑल एल्गोरिदम अच्छा है बट क्योंकि बस टाइम हमें नह
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_sjf_cross_document_hard__q_english | english | Across the course materials, why is Shortest Job First (SJF) scheduling considered difficult or practically impossible to implement? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_process_memory_cross_document_hard

- **Domain:** operating systems
- **Subject:** process management
- **Source language:** mixed
- **Source type:** mixed
- **Query type:** multi_document
- **Difficulty:** hard
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** `6aa72e4416cbab6b27d5f50b`
- **All contributing document_ids:** `6aa72e4416cbab6b27d5f50b`, `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `8bde1fee-6475-5709-b3d3-df7cc009e665`, `15197ab2-7fc0-5cc8-9860-5c0409be66ba`
- **Reviewer notes (from Claude):** *(CORRECTED in Phase 3.1)* The English PDF chunk (c_process_vs_program) covers only two of the three regions -- stack (temporary data, parameters, return addresses) and data section (global variables) -- and does NOT mention the heap. On re-reading the COMPLETE Hindi video chunk text, it is ALREADY comprehensive on its own: it covers data section, heap (runtime dynamic allocation), AND stack. The original rationale's claim that "neither chunk is fully complete" was incorrect -- the Hindi chunk alone fully answers this question. Kept as a multi-document case per instruction not to remove valid cross-language cases merely because they are difficult, but the rationale no longer overclaims that both chunks are strictly required: the English chunk is valid corroborating partial evidence, not a necessary second piece.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `8bde1fee-6475-5709-b3d3-df7cc009e665`: Lecture #6(UNIT-II) Process Concept  Informally, a process is a program in execution. A process is more than the program code, which is sometimes known as the text section. It also includes the current activity, as represented by the value of the program counter and the contents of the processor's registers. In addition, a process generally includes the process stack, which contains temporary data (such as method parameters, return addresses, and local variables), and a data section, which cont
>
> `15197ab2-7fc0-5cc8-9860-5c0409be66ba`: का जितना कोड है वो पूरा कोड है। पीसीबी इससे अलग है। है ना? मैं मेमोरी में आपको प्रोसेस किस तरह से दिखेगा उसकी इमेज दिखा रहा हूं। देन उसके ऊपर आपको मिलेगा डेटा सेक्शन जहां पे ग्लोबल वेरिएबल्स जो है हमारे हैं वो डिक्लेअर होते हैं। उससे ऊपर आपको मिलेगा हीप जहां पे रन टाइम पे अगर डायनेमिक मेमोरी एलोकेशन हम करते हैं तो वो हिप में होता है और जो हमारा पूरा एक्टिवेशन रिकॉर्ड है स्टक वो ऊपर से नीचे चलता है जिसमें पैराटर्स रिटर्न्स वेरिएबल एड्रेसेस वो सारी इनेशन रहती है। अगेन बहुत डिटेल में जाने की जरूरत 
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_process_memory_cross_document_hard__q_english | english | How is a process's memory layout (stack, heap, data section) described across the course materials? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## c_workspace_wide_scheduling_algorithms

- **Domain:** operating systems
- **Subject:** scheduling *(corrected in Phase 3.1 -- was `cpu scheduling`; see below)*
- **Source language:** mixed
- **Source type:** mixed
- **Query type:** workspace_wide
- **Difficulty:** hard
- **Workspace ID:** `6a912a1883f46878932e0eec`
- **Document ID:** null (workspace-wide -- see document_ids)
- **All contributing document_ids:** `6aa72dae16cbab6b27d5f508`, `6aa846698a7bd709c53a5f4e`, `6aaa7e8c81e2b76728b76bb6`
- **Relevant chunk_id(s):** `ae88f902-a448-573d-a7ea-a7ea2b4191f5`, `e866b283-ab34-5320-96b0-882be0919ba1`, `7d131130-e14e-597a-9cb1-f3dc5dad183e`, `b15a9c9f-c3c6-54ee-a865-5b328b74f755`
- **Reviewer notes (from Claude):** *(CORRECTED in Phase 3.1)* Deliberately workspace-wide, not document-specific: this workspace's materials discuss SJF CPU scheduling (both in the English PDF and the Hindi video), Round Robin CPU scheduling (English PDF), and FCFS DISK scheduling (Hindi video). The query was corrected from "CPU scheduling algorithms" to the broader "scheduling algorithms" (and `subject` from `cpu scheduling` to `scheduling`) because the evidence set legitimately spans both CPU and disk scheduling -- the original wording was narrower than the evidence it cited. `document_id` is intentionally null -- no single document answers this on its own; see `document_ids` for the three real documents actually contributing evidence. This is the hardest case in this dataset: it requires retrieving across 3 documents, 2 source types (pdf/youtube), and 2 source languages (english/hindi) for one query.

**Actual supporting excerpt(s) (first ~500 chars each):**

> `ae88f902-a448-573d-a7ea-a7ea2b4191f5`: the minimum average waiting time for a given set of processes. By moving a short process before a long one, the waiting time of the short process decreases more than it increases the waiting time of the long process. Consequently, the average waiting time decreases. The real difficulty with the SJF algorithm is knowing the length of the next CPU request. For long-term (or job) scheduling in a batch system, we can use as the length the process time limit that a user specifies when he submits the 
>
> `e866b283-ab34-5320-96b0-882be0919ba1`: . Since it requires another 20 milliseconds, it is preempted after the first time quantum, and the CPU is given to the next process in the queue, process P2. Since process P2 does not need 4 milliseconds, it quits before its time quantum expires. The CPU is then given to the next process, process P3. Once each process has received 1 time quantum, the CPU is returned to process P1 for an additional time quantum. The resulting RR schedule is The average waiting time is 17/3 = 5. 66 milliseconds. I
>
> `7d131130-e14e-597a-9cb1-f3dc5dad183e`: टल आईड ि य ा ह ो सकत ा ह ै द ै ट इज़ एफस ी एफएस ज ो हर जगह हम य ू ज़ करत े आए ह ै ं । त ो एफस ी एफएस क ् य ा ब ो ल े ग ा सर? वो यह बोलेगा कि फॉर एग्जांपल अगर यह हमारे पास सारे ट्रैक नंबर हैं तो मैं जैसे यहां शायद दिख भी रहा है। मेरे को फर्क नहीं पड़ता कि आपका कौन सा ट्रैक नंबर आगे है, कौन सा पीछे है या मुझे फिजिकली कितना मूव करना पड़ेगा। जो रिक्वेस्ट पहले आई थी उसको हम पहले आंसर करेंगे। जो बाद में आई थी उसको बाद में आंसर करेंगे। अब ये है तो वैलिड कोई प्रॉब्लम नहीं है इसमें। बट जैसा आप देख रहे हैं 
>
> `b15a9c9f-c3c6-54ee-a865-5b328b74f755`: ह ै । थ ् य ो र ि ट ि कल आईड ि य ा ह ै । आप ब ो ल े ं ग े इ ं प ् ल ी म े ं ट े बल क ् य ो ं नह ी ं ह ै? भाई सोचो पूरा का पूरा जो एल्गोरिदम है वो इस बात पे टिका हुआ है कि किसका बस टाइम क्या है? लेकिन सवाल ये है जब प्रोसेस एग्जीक्यूशन के लिए आता है क्या प्रोसेस को पहले से पता होता है मेरा बस टाइम क्या है क्या प्रोसेस को पता है कि वो ओवरऑल CPU पे कितने समय के लिए एग्जीक्यूट करेगा ऑब्वियसली नहीं पता होता नहीं पता होता ना सो दैट इज़ अ प्रॉब्लम तो ये ओवरऑल एल्गोरिदम अच्छा है बट क्योंकि बस टाइम हमें नह
>

| query_id | query_language | query | review status (fill in) |
|---|---|---|---|
| c_workspace_wide_scheduling_algorithms__q_english | english | *(Phase 3.1: "CPU" dropped from the query -- evidence includes FCFS disk scheduling, not only CPU scheduling)* What scheduling algorithms are discussed in this workspace's course materials? | ☐ approved / ☐ rejected / ☐ needs edit |

---

## Corpus inspection summary (for reviewer awareness)

- **Workspaces:** 2 total. `6a912a1883f46878932e0eec` (9 of 10 documents) and `6a8de2d7e43679cbe2ee243d` (1 document -- the DBMS textbook).
- **Documents:** 10 document_ids total, but only **6 genuinely distinct content items**:
  1. An OS textbook (PDF, English) -- ingested **5 separate times** as document_ids `6aa90e314ac03b89c7624ccb`, `6aa72e4416cbab6b27d5f50b`, `6aa846698a7bd709c53a5f4e`, `6aa72dae16cbab6b27d5f508`, and `6aa90d9f4ac03b89c7624cc8`. Direct inspection confirmed all 92 checked shared page numbers are byte-for-byte identical text across all five -- this is one real document duplicated, not five distinct sources. Concepts above cite whichever one of the five copies happens to hold the relevant page.
  2. An OS lecture in Hindi/Devanagari (YouTube, `6aaa7e8c81e2b76728b76bb6`, 177 chunks, ~152 words/chunk average) -- usable, rich.
  3. An OS lecture in English (YouTube, `6aaa4cd56eee7990194e5168`, 527 chunks) -- **UNUSABLE**: chunks average ~6.7 words each (range 1-10), too fragmented for any chunk to stand alone as answerable evidence.
  4. A DBMS textbook (PDF, English, `6aa8457c8a7bd709c53a5f46`, 250 chunks) -- usable, rich; the only document in its workspace.
  5. A Maharashtra CET admissions allotment list (PDF, `6aa72df916cbab6b27d5f50a`, 120 chunks) -- **UNUSABLE**: not educational content.
  6. A stray MP4 (`6aa90eb64ac03b89c7624cce`) with exactly 1 chunk whose entire text is the single word "you" -- **UNUSABLE**.
- **Domains represented:** exactly 2 -- operating systems and database management systems. No other subject exists anywhere in this corpus; none was invented.
- **Source types represented:** pdf, youtube. (mp4 exists but its only chunk is unusable.)
- **Source languages:** english and hindi (Devanagari) only. A scan of all 1473 non-Devanagari chunks for common Hinglish markers (hai, kya, nahi, matlab, toh, bhai, etc.) found zero matches -- no genuine Hinglish-SOURCE content exists in this corpus. Hinglish appears only as a QUERY language above, never fabricated as source content.
- **Why OS has more entries than DBMS:** OS genuinely has 2 usable sources (the textbook + the Hindi lecture) vs. DBMS's 1 (the textbook) -- this dataset gives each of the 3 usable sources an EQUAL 8 concepts / 24 entries, which already over-weights DBMS relative to raw OS document count, rather than following the corpus's raw 9-vs-1 document skew.
- **Multi-document / cross-language / workspace-wide hard cases:** 3 entries (`c_sjf_cross_document_hard`, `c_process_memory_cross_document_hard`, `c_workspace_wide_scheduling_algorithms`) deliberately cite `relevant_chunk_ids` spanning 2-3 real document_ids and, in one case, 2 source languages -- these are the only entries using `source_language: "mixed"` and a `document_ids` array instead of a single `document_id`.
- **Out of scope for this dataset (flagged, not solved here):** "irrelevant/unanswerable question" and "conversational/casual message" behaviors are real product requirements but do not fit a Recall@k/MRR retrieval schema (which requires a non-empty `relevant_chunk_ids`) -- they would need a separate grounding/refusal evaluation dataset, not an extension of this one.