Example 1. Sources:
<source id="S1" document="Services Agreement" pages="4" section="Section 9.2 Termination">Either party may terminate
this Agreement upon thirty (30) days' prior written notice to the other party.</source>
<source id="S2" document="Services Agreement" pages="5" section="Section 11 Governing Law">This Agreement shall be
governed by the laws of the State of Delaware.</source>
Question: How can the agreement be terminated, and what is the liability cap?
Answer JSON:
{"answerable": true, "sentences": [
 {"text": "Either party may terminate the agreement with thirty (30) days' prior written notice to the other party.",
  "citations": [{"source": "S1", "quote": "Either party may terminate this Agreement upon thirty (30) days' prior written notice"}]},
 {"text": "The provided documents do not address this.", "citations": []}]}

Example 2. Sources:
<source id="S1" document="Example Code" pages="12" section="Section 447 Punishment for criminal trespass">Whoever
commits criminal trespass shall be punished with imprisonment of either description for a term which may extend to
three months, or with fine which may extend to five hundred rupees, or with both.</source>
Question: What is the punishment for trespassing on a 5 acre farm?
Note from the search step: the size of the land (5 acres)
Answer JSON:
{"answerable": true, "sentences": [
 {"text": "The provided documents do not address a different punishment based on the size of the land.",
  "citations": []},
 {"text": "Whoever commits criminal trespass shall be punished with imprisonment of either description for a term which may extend to three months, or with fine which may extend to five hundred rupees, or with both.",
  "citations": [{"source": "S1", "quote": "Whoever commits criminal trespass shall be punished with imprisonment of either description for a term which may extend to three months"}]}]}
