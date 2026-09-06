//! Run against an actual signed artifact; never requires the private key.
use base64::{engine::general_purpose::STANDARD, Engine};
use minisign_verify::{PublicKey, Signature};

#[test]
#[ignore = "requires LOOPX_TEST_SIGNED_ARCHIVE from a signed release build"]
fn shipped_public_key_accepts_artifact_and_rejects_tampering() {
    let path = std::env::var("LOOPX_TEST_SIGNED_ARCHIVE").unwrap();
    let config: serde_json::Value =
        serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
    let key = STANDARD
        .decode(config["plugins"]["updater"]["pubkey"].as_str().unwrap())
        .unwrap();
    let key = PublicKey::decode(std::str::from_utf8(&key).unwrap()).unwrap();
    let signature = std::fs::read_to_string(format!("{path}.sig")).unwrap();
    let signature = STANDARD.decode(signature.trim()).unwrap();
    let signature = Signature::decode(std::str::from_utf8(&signature).unwrap()).unwrap();
    let mut bytes = std::fs::read(path).unwrap();
    key.verify(&bytes, &signature, true).unwrap();
    bytes[0] ^= 1;
    assert!(key.verify(&bytes, &signature, true).is_err());
}
