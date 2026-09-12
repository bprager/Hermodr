# Backup Recovery Material

`backup-passphrase.sops.json` is the SOPS/age-encrypted recovery copy of the passphrase used for Hermóðr backup archives. It is ciphertext and may be committed. Never commit the age identity, decrypted passphrase, Bitwarden export, vault session, or vault credentials.

Bernd is the recovery-key custodian. The corresponding Hermóðr-specific age identity must be stored in Bitwarden independently of Odin and Saga. Recovery requires checking out this repository, retrieving that identity from Bitwarden, decrypting the SOPS file into a protected temporary file, and running `backup-verify` plus `restore-test` against a Saga archive.

The Bitwarden item should be a secure note named `Hermodr backup recovery age identity`. Store the complete age identity file as its note or attachment. Do not store the backup passphrase separately unless a second explicitly approved recovery method is desired. After saving it, retrieve the identity onto a machine other than Odin or Saga and verify:

```shell
SOPS_AGE_KEY_FILE=/protected/retrieved-identity \
  sops decrypt --output-type binary \
  --output /protected/temporary-passphrase \
  config/recovery/backup-passphrase.sops.json
hermodr --config /protected/config.json admin restore-test \
  --archive /path/to/saga-copy.tar.gpg \
  --passphrase-file /protected/temporary-passphrase
```

Delete the temporary passphrase immediately after the test through the approved secure-file disposal mechanism. Remove Odin's staging copy of the age identity only after the Bitwarden retrieval test succeeds.

Do not replace either side independently: rotate the runtime passphrase, SOPS ciphertext, and Bitwarden identity through one audited recovery drill.
