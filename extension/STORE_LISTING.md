# Chrome Web Store — submission pack (TRL Composer)

## Single purpose (required field)
Compress the text in the Claude.ai message box before the user sends it, so the
message uses fewer tokens — with a preview and a guarantee that numbers are kept.

## Name
TRL Composer — token saver for Claude.ai

## Short description (<=132 chars)
Shrink pasted context in Claude.ai before you send it, so you use fewer tokens. Works offline. Preview + number-guard included.

## Detailed description
Long prompts and pasted documents eat into Claude usage fast. TRL Composer adds a
Compress button to the Claude.ai message box: click it, and repeated lines and
boilerplate are stripped out before you send — so the same request costs fewer
tokens and you get more out of your plan.

• Works with no setup — compresses right in your browser. (Power users can run the
  optional local engine for stronger compression.)
• Preview first — you always see the shorter version and choose to use it or keep
  your original. Nothing is ever sent for you.
• Number-guard — every number in your text (amounts, IDs, dates) is guaranteed to
  survive compression.
• Private — your text never leaves your computer. No accounts, no tracking, no ads.

Best for pasting long context (docs, logs, repeated instructions). Short chats gain
little. Helps most on token-metered usage.

## Category
Productivity

## Permission justifications (for the review form)
- storage: remember the user's local settings in their browser.
- host access to claude.ai: place the Compress button and read/replace the message-box text, only on click. No remote servers; all compression happens in the browser.
- host access to claude.ai: place the Compress button and read/replace the message-box text on click.

## Privacy policy URL
Use the public repo copy:
https://github.com/AryanGonsalves/trl-token-reduction/blob/main/extension/PRIVACY.md

## Assets you still need to provide (can't be auto-generated)
- [x] Screenshot 1280x800 provided: `store-screenshot-1280x800.png` (this folder).
- [ ] 128x128 store icon (included: icons/icon128.png).
- [ ] Optional 440x280 small promo tile.

## Submission steps
1. Create a Chrome Web Store developer account (one-time $5 fee) at
   https://chrome.google.com/webstore/devconsole
2. Upload trl-composer-extension-v0.1.0.zip.
3. Fill the listing using the copy above; add the screenshot and privacy-policy URL.
4. Submit for review (typically a few days).

## Data-use disclosure (Dashboard 'Privacy' tab)
Declare: does NOT collect or use user data. No data leaves the user's machine;
compression runs in the browser. Check the 'I do not sell/transfer data' boxes.
