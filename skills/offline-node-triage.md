---
name: offline-node-triage
description: Use when one or more PCs/servers go offline — how to judge scope, urgency, and the next step. Read-only advice.
---

When a host is reported offline:

1. Get the current down list (get_down_nodes) and how long each has been offline.
2. Judge scope — this is the key question:
   - ONE host down → likely that machine (powered off, sleeping, cable). Lower urgency.
   - MANY hosts on the same area/subnet down together → suspect a shared cause: a
     switch, PoE, or power circuit. Higher urgency, page IT.
3. Weigh work hours: a workstation off after hours is usually fine; a server or a
   work-hours outage of a needed host is page-worthy.
4. Next step for IT: name the host(s), the offline duration, and the most likely cause
   from the scope judgement (single-machine vs network/power). Do not take action —
   report and recommend.
