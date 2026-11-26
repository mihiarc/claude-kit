# kit-secret

Sets secrets without anyone pasting them into a chat. A value goes from a hidden prompt, or from a generator, straight into the local store (the macOS keychain through `security`, or `secret-tool` on Linux), and from there through a pipe into `gh secret set`, which reads standard input when it gets no `--body`. The value is never printed, never written to a file and never put in a command's arguments, where the process list would show it.

The installer's shell line puts this folder on `PATH`. Without the installer, add it yourself or call the script by its full path.

## The three paths

**A token minted in a dashboard.** Run this in your own terminal tab. It asks with a hidden prompt (twice on macOS), so it needs a terminal, and a `!` command in Claude's prompt or Claude's Bash tool has none; there it refuses and says so. When the clipboard still holds the value after a successful save, it clears it.

    kit-secret save stripe-live --gh STRIPE_KEY --repo owner/repo

**A value already in the store.** Claude can run this one, since it never sees the value.

    kit-secret gh stripe-live STRIPE_KEY --repo owner/repo

**A value to generate.** It makes random bytes as hex, saves them in the store and sets the GitHub secret from the same variable, so the two can't diverge.

    kit-secret new webhook-signing --gh WEBHOOK_SECRET --repo owner/repo

Flags after the secret name go to `gh secret set` (`--repo`, `--env`, `--app`, `--org`); `--body`, `--env-file` and `--no-store` are refused. `--account` picks the store item's account, defaulting to `$USER` when saving and to any account when reading. `save` and `new` refuse to overwrite an existing item without `--replace`. `KIT_SECRET_STORE=keychain` or `secret-tool` overrides the store chosen from the OS.

A read of a missing item fails with a message and sets nothing.

It needs `perl` (on macOS and most Linux systems already). Inside the script a value travels as hex, so a multi-line key, a tab or a non-ASCII byte reaches GitHub byte for byte. On macOS it reads the keychain with `security find-generic-password -g` rather than `-w`, because `-w` prints a value with any unprintable byte as bare hex, which can't be told apart from a value that is itself hex.

## Tests

    python3 -m unittest discover extras/secrets/tests

They run the script against fake `security`, `gh` and clipboard tools that log every argument list and environment, drive `save` through a pseudo-terminal, and check that a made-up value never reaches an argument list, an environment, a temp file or the output. The fake `security` prints values as the real one does: in hex when a byte is unprintable, and under `-g` also when the value holds a backslash.
