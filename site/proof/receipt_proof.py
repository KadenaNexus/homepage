#!/usr/bin/env python3
"""Receipt Proof by Kadena Nexus: make a commitment, keep a receipt, verify one.

    python3 receipt_proof.py commit  <file>                     make the salt and the commitment (nothing leaves this machine)
    python3 receipt_proof.py receipt <file> <answer.json>       put the paid answer and your salt together into the receipt
    python3 receipt_proof.py verify  <file> <receipt.json>      check a file against its receipt, straight from a Kadena node

Needs Python 3.8 or later and nothing else.

What a receipt shows: this exact file matches a commitment recorded in the
registry contract on Kadena, in the block given. It does not show who wrote
the file, when it was delivered, whether its content is correct, or that no
other version exists.

How the commitment is made:
    fileSha256 = SHA-256 of the file's bytes
    salt       = 32 random bytes, made here and kept by you
    commitment = SHA-256(the 32 salt bytes followed by the 32 fileSha256 bytes)
Only the commitment is sent anywhere. Keep the file and the receipt together;
the file must stay byte for byte as it was, or it no longer matches.

Test example: file bytes "Kadena Nexus Receipt Proof sample report" and a
line feed, salt 00 01 02 ... 1f, give commitment
b8b0c104743ced5f41efc910653e4daef8b6566f0bd2cb738ad5c8336cf23beb.
"""
import base64, hashlib, json, os, re, secrets, sys, time, urllib.error, urllib.request

SERVICE = "https://agentpay.kadena.ws"
TYPE, VERSION, SCHEME = "kadena-nexus-receipt-proof", 1, "sha256(salt32 || fileSha256_32), hex"
HEX64 = re.compile(r"[0-9a-f]{64}")
REQUEST_KEY = re.compile(r"[A-Za-z0-9_\-]{43}")
SHOWS = "This exact file matches a commitment recorded in the registry contract on Kadena, in the block given."
DOES_NOT_SHOW = "Who wrote the file, when it was delivered, whether its content is correct, or that no other version exists."

# The registry contracts this verifier accepts, and nothing else: a receipt
# that names another network, chain or contract is refused, and so is a
# contract under an accepted name whose code is not the one listed here.
# "depth": blocks on top of a record before it counts as confirmed.
# The registry contracts this verifier accepts. Deployed 2026-11-22 (request key
# MgcCl8MoXFQ5lxr1mTjrzcUNmfzgdu2DZE29Fg_aWok, block 7426589); the hash was read
# from two nodes. Kept equal to deployments.json, which the page is built from.
DEPLOYMENTS = [
    {"id": 1, "network": "mainnet01", "chain": "1",
     "module": "n_bae9408ba9655ac34901da87088e9b776941d0d3.receipt-proof-v1",
     "moduleHash": "Fjg0Bi6oq_I4fW6Rnv3ARYNyVHrDL34vq5MqC-u6nYk", "depth": 10,
     "nodes": ["https://api.chainweb-community.org", "https://chainweb.chaddex.com"]},
]

MATCH, NO_MATCH, UNAPPROVED, UNAVAILABLE, NOT_RECORDED, NOT_CONFIRMED = (
    "match", "no match", "unapproved contract", "verification unavailable", "not recorded", "recorded, not yet confirmed")


# ---- the commitment

def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def commitment_of(salt_hex: str, file_sha256_hex: str) -> str:
    """SHA-256 over the raw bytes: 32 of salt, then 32 of the file's SHA-256. Never over the hex text."""
    for value in (salt_hex, file_sha256_hex):
        if not isinstance(value, str) or not HEX64.fullmatch(value):
            raise ValueError("salt and fileSha256 are 64 lower-case hex characters each")
    return hashlib.sha256(bytes.fromhex(salt_hex) + bytes.fromhex(file_sha256_hex)).hexdigest()


def new_commitment(path: str, salt_hex: str = None) -> dict:
    """What a buyer keeps before paying: the file's fingerprint, a fresh salt and the commitment."""
    digest = file_sha256(path)
    salt = salt_hex or secrets.token_bytes(32).hex()
    return {"fileSha256": digest, "salt": salt, "commitment": commitment_of(salt, digest)}


def make_receipt(kept: dict, answer: dict) -> dict:
    """The receipt: what the buyer kept, with what the service answered. Raises
    ValueError when the two do not belong together."""
    commitment = commitment_of(kept["salt"], kept["fileSha256"])
    if answer.get("commitment") != commitment:
        raise ValueError("the answer is for another commitment than this file and salt give")
    for name in ("network", "chain", "module"):
        if not isinstance(answer.get(name), str) or not answer[name]:
            raise ValueError(f"the answer has no {name}")
    receipt = {"type": TYPE, "version": VERSION, "commitmentScheme": SCHEME, "fileSha256": kept["fileSha256"],
               "salt": kept["salt"], "commitment": commitment, "network": answer["network"], "chain": answer["chain"],
               "module": answer["module"], "requestKey": answer.get("requestKey"), "issuedAt": answer.get("issuedAt")}
    for name in ("blockHeight", "blockTime", "blockHeaderTime", "blockHash"):      # present once the service has seen it confirmed
        if answer.get(name) is not None:
            receipt[name] = answer[name]
    return receipt


def buy(path: str, pay, keep=None, service: str = SERVICE, salt_hex: str = None) -> dict:
    """A receipt for a file in one call. `pay(url)` is your own function that
    makes a paid x402 GET and returns the answer as a dict; this module pays
    nothing itself. `keep(kept)` is called with the salt BEFORE anything is
    paid: save it, since a paid receipt is worthless without its salt."""
    kept = new_commitment(path, salt_hex)
    if not callable(keep):
        raise TypeError("A keep callback must save the commitment before payment")
    keep(kept)
    return make_receipt(kept, pay(f"{service}/v1/proof/{kept['commitment']}"))


# ---- reading a Kadena node (the Pact API of one chain)

def _request_key(cmd: str) -> str:
    return base64.urlsafe_b64encode(hashlib.blake2b(cmd.encode(), digest_size=32).digest()).rstrip(b"=").decode()


def _post(url: str, body: dict, timeout: float):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read(2_000_000))


def local(node: str, network: str, chain: str, code: str, timeout: float = 20):
    """Run read-only code on a node. Returns the data, or raises OSError (no
    usable answer) or ValueError (the node answered, and the code failed)."""
    cmd = json.dumps({"networkId": network, "payload": {"exec": {"code": code, "data": {}}}, "signers": [],
                      "meta": {"chainId": chain, "sender": "", "gasLimit": 20000, "gasPrice": 0.00000001, "ttl": 600,
                               "creationTime": int(time.time()) - 30},
                      "nonce": "receipt-proof-verify"}, separators=(",", ":"))
    url = f"{node.rstrip('/')}/chainweb/0.0/{network}/chain/{chain}/pact/api/v1/local?signatureVerification=false"
    try:
        reply = _post(url, {"hash": _request_key(cmd), "sigs": [], "cmd": cmd}, timeout)
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise OSError(f"{node}: {err}")
    result = reply.get("result") if isinstance(reply, dict) else None
    if not isinstance(result, dict) or result.get("status") not in ("success", "failure"):
        raise OSError(f"{node}: the answer has an unexpected shape")
    if result["status"] != "success":
        raise ValueError(json.dumps(result.get("error"))[:300])
    return result.get("data")


def header_time(node: str, network: str, chain: str, request_key: str, timeout: float = 20):
    """(header time, block hash, block height) of the block a transaction is in, when the node still has it; else None."""
    url = f"{node.rstrip('/')}/chainweb/0.0/{network}/chain/{chain}/pact/api/v1/poll"
    try:
        meta = (_post(url, {"requestKeys": [request_key]}, timeout).get(request_key) or {}).get("metaData") or {}
        micros = meta.get("blockTime")
        if isinstance(micros, bool) or not isinstance(micros, int):
            return None
        return (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(micros / 1_000_000)), meta.get("blockHash"), meta.get("blockHeight"))
    except Exception:
        return None


def _int(value) -> int:
    if isinstance(value, dict) and "int" in value:
        value = value["int"]
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("not an integer")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value):
        raise ValueError("invalid block height")
    height = int(value)
    if not 0 <= height <= 2**53 - 1:
        raise ValueError("invalid block height")
    return height


def _time(value) -> str:
    if isinstance(value, dict):
        value = value.get("time") or value.get("timep")
    if not isinstance(value, str):
        raise ValueError("not a time")
    return value


# ---- verifying

def deployment_for(receipt: dict, deployments=None):
    for d in (DEPLOYMENTS if deployments is None else deployments):
        if (receipt.get("network"), receipt.get("chain"), receipt.get("module")) == (d["network"], d["chain"], d["module"]):
            return d
    return None


def verify(file_path: str, receipt: dict, deployments=None, nodes=None, timeout: float = 20) -> dict:
    """Check a file against its receipt. The answer's "result" is one of:
      match                        the file matches a record that is confirmed on Kadena
      no match                     this file and this receipt do not belong together
      unapproved contract          the receipt names a network, chain or contract this verifier does not accept
      verification unavailable     no node gave a usable answer; says nothing about the file
      not recorded                 file and receipt belong together, and the contract has no such record
      recorded, not yet confirmed  the record is there, and not deep enough yet
    The node is asked only what the approved contract holds. Nothing in the receipt is taken on trust."""
    out = {"result": NO_MATCH, "shows": SHOWS, "doesNotShow": DOES_NOT_SHOW}
    try:
        if receipt.get("type") != TYPE or receipt.get("version") != VERSION:
            return dict(out, reason="this is not a Receipt Proof receipt of version 1")
        digest = file_sha256(file_path)
        commitment = commitment_of(receipt["salt"], digest)
    except (KeyError, ValueError, TypeError, AttributeError):
        return dict(out, reason="the receipt cannot be read")
    out.update(fileSha256=digest, commitment=commitment)
    if commitment != receipt.get("commitment"):
        return dict(out, reason="the file is not the one this receipt was made for, or it was changed")
    found = deployment_for(receipt, deployments)
    if found is None:
        return dict(out, result=UNAPPROVED, reason="the receipt names a network, chain or contract that is not on this verifier's list")
    out.update(network=found["network"], chain=found["chain"], module=found["module"])
    module, problems = found["module"], []
    for node in (nodes or found["nodes"]):
        try:
            code_hash = local(node, found["network"], found["chain"], f'(at "hash" (describe-module "{module}"))', timeout)
            if code_hash != found["moduleHash"]:
                return dict(out, result=UNAPPROVED, node=node, reason="the contract under this name is not the one this verifier accepts")
            data = local(node, found["network"], found["chain"],
                         f'{{ "height": (at "block-height" (chain-data)), '
                         f'"rows": (if ({module}.is-recorded "{commitment}") [({module}.get-receipt "{commitment}")] []) }}', timeout)
            height, rows = _int(data["height"]), data["rows"]
            if not isinstance(rows, list) or len(rows) > 1:
                raise OSError("the answer has an unexpected shape")
            if not rows:
                return dict(out, result=NOT_RECORDED, node=node, reason="the contract has no record of this commitment")
            row = rows[0]
            recorded, contract_time, tx = _int(row["block-height"]), _time(row["block-time"]), row["tx"]
            if recorded > height:
                raise ValueError("record is above the chain height")
            if not isinstance(tx, str) or not REQUEST_KEY.fullmatch(tx):
                raise OSError("the answer has an unexpected shape")
        except OSError as err:
            problems.append(str(err))
            continue
        except (ValueError, KeyError, TypeError) as err:
            problems.append(f"{node}: {err}")
            continue
        out.update(node=node, blockHeight=recorded, contractTime=contract_time, transaction=tx,
                   confirmations=height - recorded, confirmationsNeeded=found["depth"])
        header = header_time(node, found["network"], found["chain"], tx, timeout)
        if header:
            out.update(blockHeaderTime=header[0], blockHash=header[1])
        if height - recorded < found["depth"]:
            return dict(out, result=NOT_CONFIRMED, reason=f"in a block, and confirmed once {found['depth']} blocks deep")
        return dict(out, result=MATCH)
    return dict(out, result=UNAVAILABLE, reason="no node gave a usable answer; this says nothing about the file", problems=problems)


# ---- a receipt as a link (for a QR code): everything but the file's fingerprint, after the #

def _b64(hex_text: str) -> str:
    return base64.urlsafe_b64encode(bytes.fromhex(hex_text)).rstrip(b"=").decode()


def _hex(b64: str) -> str:
    return base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).hex()


def to_fragment(receipt: dict, deployments=None) -> str:
    found = deployment_for(receipt, deployments)
    if found is None:
        raise ValueError("the receipt's contract is not on the list")
    return ".".join(["1", str(found["id"]), _b64(receipt["commitment"]), _b64(receipt["salt"]), receipt.get("requestKey") or ""])


def from_fragment(fragment: str, deployments=None) -> dict:
    parts = fragment.lstrip("#").split(".")
    if len(parts) != 5 or parts[0] != "1":
        raise ValueError("not a Receipt Proof link")
    found = next((d for d in (DEPLOYMENTS if deployments is None else deployments) if str(d["id"]) == parts[1]), None)
    if found is None:
        raise ValueError("the link names a contract that is not on the list")
    # Each value is base64url (as to_fragment writes it) or, for links an agent builds by hand, 64 hex characters.
    value = lambda part: part.lower() if HEX64.fullmatch(part.lower()) else _hex(part)       # noqa: E731
    try:
        commitment, salt = value(parts[2]), value(parts[3])
    except ValueError:
        raise ValueError("not a Receipt Proof link")
    if not HEX64.fullmatch(commitment) or not HEX64.fullmatch(salt) or (parts[4] and not REQUEST_KEY.fullmatch(parts[4])):
        raise ValueError("not a Receipt Proof link")
    return {"type": TYPE, "version": VERSION, "commitmentScheme": SCHEME, "salt": salt, "commitment": commitment,
            "network": found["network"], "chain": found["chain"], "module": found["module"], "requestKey": parts[4] or None}


# ---- the command line

def main(argv) -> int:
    if len(argv) == 3 and argv[1] == "commit":
        kept = new_commitment(argv[2])
        where = argv[2] + ".commitment.json"
        fd = os.open(where, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)        # never over an earlier one: its salt may be in a paid receipt
        with os.fdopen(fd, "w") as f:
            json.dump(kept, f, indent=2)
        print(f"Kept in {where} (your salt is in it; keep it).\nCommitment: {kept['commitment']}\n"
              f"Pay for:    {SERVICE}/v1/proof/{kept['commitment']}\nStatus:     {SERVICE}/v1/proof/status/{kept['commitment']}")
        return 0
    if len(argv) == 4 and argv[1] == "receipt":
        with open(argv[2] + ".commitment.json") as f:
            kept = json.load(f)
        with open(argv[3]) as f:
            answer = json.load(f)
        receipt = make_receipt(kept, answer)
        where = argv[2] + ".receipt.json"
        with open(where, "w") as f:
            json.dump(receipt, f, indent=2)
        print(f"Receipt written to {where}. Keep it with the file; you can verify them later for free.")
        return 0
    if len(argv) == 4 and argv[1] == "verify":
        with open(argv[3]) as f:
            receipt = json.load(f)
        found = verify(argv[2], receipt)
        print(json.dumps(found, indent=2))
        return 0 if found["result"] == MATCH else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (OSError, ValueError, KeyError) as err:
        print(f"Could not do that: {err}", file=sys.stderr)
        sys.exit(2)
