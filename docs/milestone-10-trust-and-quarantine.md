# Milestone 10: Basic Trust and Quarantine Manual Test

This test verifies that awareness remains visible without implying trust, that
SERVICE usability is limited for unknown providers, and that blocked or
sensitive claims are not propagated.

Cryptographic signatures, invite tokens, and a full administration UI are not
part of this milestone.

## Trust Administration

Each node stores local decisions in its data directory as trust.json. The
default policy mode is review, and an unlisted node ID has state unknown.

Use these commands while the daemon for that data directory is stopped:

~~~powershell
python streetmeshd.py --data-dir .\m10-data\node-b --list-trust
python streetmeshd.py --data-dir .\m10-data\node-b --trust-node <NODE_A_ID>
python streetmeshd.py --data-dir .\m10-data\node-b --block-node <NODE_A_ID>
~~~

Restart the daemon after changing trust so it reloads trust.json.

## Unknown Awareness

1. Configure Node A with the temperature service from
   examples/services.example.json.
2. Start Node B with a fresh data directory and no trust entry for Node A.
3. Start Node A.
4. Confirm Node B logs policy acceptance for Node A's NODE claim:

   ~~~text
   INFO streetmesh.daemon: Policy accepted: type=NODE origin=<NODE_A_ID> trust_state=unknown reason=node-unknown ko_id=<KO_ID>
   ~~~

5. Confirm Node B logs limited acceptance for Node A's SERVICE claim:

   ~~~text
   INFO streetmesh.daemon: Policy accepted-limited: type=SERVICE origin=<NODE_A_ID> trust_state=unknown reason=service-unknown ko_id=<KO_ID>
   ~~~

6. Inspect Node B's awareness.json. The Node A entry should contain trust_state
   unknown. Its temperature service should contain trust_state unknown and
   accepted_limited true.

This proves discovery still works while unknown services are not represented
as trusted usable services.

## Trusted Provider

1. Stop Node B.
2. Mark Node A trusted:

   ~~~powershell
   python streetmeshd.py --data-dir .\m10-data\node-b --trust-node <NODE_A_ID>
   ~~~

3. Restart Node B and leave Node A running.
4. On Node A's next SERVICE announcement, confirm Node B logs:

   ~~~text
   INFO streetmesh.daemon: Policy accepted: type=SERVICE origin=<NODE_A_ID> trust_state=trusted reason=service-trusted ko_id=<KO_ID>
   ~~~

5. Confirm the refreshed service has trust_state trusted and accepted_limited
   false.

## Blocked Origin

Use a fresh Node C data directory so old awareness cannot obscure the result.

1. Record Node A's ID, then mark it blocked for Node C:

   ~~~powershell
   python streetmeshd.py --data-dir .\m10-data\node-c --block-node <NODE_A_ID>
   ~~~

2. Start Node C, then leave Node A announcing.
3. Confirm Node C logs rejected NODE and SERVICE claims:

   ~~~text
   INFO streetmesh.daemon: Policy rejected: type=NODE origin=<NODE_A_ID> trust_state=blocked reason=origin-blocked ko_id=<KO_ID>
   INFO streetmesh.daemon: Policy rejected: type=SERVICE origin=<NODE_A_ID> trust_state=blocked reason=origin-blocked ko_id=<KO_ID>
   ~~~

4. Confirm Node A is absent from Node C's awareness entries and no matching
   Gossip forwarded line appears for those Knowledge Object IDs.

## Sensitive Claims

Unknown GATEWAY, FEDERATION, and INTRODUCTION claims are held in quarantine.json
and are not forwarded. A quarantined decision is logged as:

~~~text
INFO streetmesh.daemon: Policy quarantined: type=GATEWAY origin=<NODE_ID> trust_state=unknown reason=review-required-gateway ko_id=<KO_ID>
~~~

The test passes when unknown awareness remains visible with explicit trust
metadata, trusted SERVICE claims are accepted normally, and blocked or
quarantined claims are neither accepted into awareness nor gossiped.
