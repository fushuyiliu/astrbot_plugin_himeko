# Himeko Companion for AstrBot

[中文](README.md) | English

> Himeko is an unofficial AI interaction plugin for AstrBot, built around the character background of Himeko from *Honkai: Star Rail*.

This is an independently made, installable AstrBot plugin release candidate. It provides an optional Himeko-style interaction prompt, explicit owner-only memory, one-shot reminders, and local attachment Q&A that requires confirmation before processing.

This project integrates with [AstrBot](https://github.com/AstrBotDevs/AstrBot), but is not affiliated with or endorsed by AstrBot or the rights holders of *Honkai: Star Rail*. It contains no official character artwork, logos, audio, lines, or game assets. Follow the applicable platform and intellectual-property rules.

## Design highlights

- Safe by default: memory, reminders, and attachments stay off until an exact owner ID is configured.
- Private owner only: sensitive reads and writes reject group messages and non-owners; an AstrBot `platform_id` can be locked as well.
- Own data directory: the plugin writes only below `data/plugin_data/astrbot_plugin_himeko/` and never reads a desktop, personal profile, knowledge base, or arbitrary host path.
- Explicit memory: facts are stored only through `/remember`-style explicit intent; common key, password, code, and identity-number patterns are rejected.
- Confirmed attachments: files are parsed locally first. Only after confirmation are extracted text and the question sent to the current AstrBot conversation model. The original file is removed after the answer or expiry.
- No blind re-delivery: a reminder needs a freshly confirmed private context in the current process. After a restart or invalid context it is marked undeliverable rather than sent to an old session.

## Scope

| Feature | Default | Description |
| --- | --- | --- |
| Himeko interaction prompt | Off | Adds a general, unofficial role-expression prompt to the configured owner's private conversation. The model and persona remain configured in AstrBot. |
| Owner memory | Off | Manually save, list, and delete up to 100 concise facts. |
| One-shot reminders | Off | Delivers only once to a currently verified owner private context. |
| Attachment Q&A | Off | PDF, DOCX, HTML, and Markdown up to 20 MB; OCR for scanned PDF pages is an optional local dependency. |

The first release deliberately excludes personal-profile reading, cloud deployment, automatic archiving, group memory, shared multi-user memory, and automatic third-party delivery.

## Install and first interaction

### 1. Prepare AstrBot and a model

1. Install and start AstrBot following the [AstrBot documentation](https://docs.astrbot.app/).
2. Configure your message platform and model provider in the AstrBot WebUI. Keep model keys in AstrBot's own configuration; **never** put them in this plugin's configuration, source code, or issues.
3. You may configure an AstrBot persona for the private conversation. The plugin's Himeko interaction prompt is an optional supplement, not a replacement for AstrBot's model or persona selection.

### 2. Install the plugin

After the public repository is released, run this from AstrBot's `data/plugins` directory:

```powershell
git clone https://github.com/fushuyiliu/astrbot_plugin_himeko.git
```

You may also copy this complete directory to `AstrBot/data/plugins/astrbot_plugin_himeko/`. Its root must contain `metadata.yaml` and `main.py` directly.

Restart AstrBot or reload the plugin from the WebUI's Plugins page. AstrBot installs the base attachment parsing dependencies from `requirements.txt`.

### Work with a public AstrBot configuration repository

This plugin repository can work alongside a public AstrBot configuration repository, while staying fully independent:

- The **configuration repository** may contain sanitized AstrBot setup instructions, platform/model templates, and compatibility notes. It must not commit owner IDs, model keys, platform tokens, real chat records, databases, logs, or production configuration files.
- This **plugin repository** contains only installable plugin source, dependencies, documentation, and tests. It must not copy runtime configuration from the configuration repository or read it through a Git submodule or automatic sync script.
- The installation order is: generic AstrBot preparation from the configuration repository, install this plugin, then enter the owner ID and desired switches locally. Owner IDs and credentials remain in the user's own AstrBot configuration.
- The repositories coordinate only through version notes: plugin 1.0.0 requires AstrBot `>=4.28,<5`. Update compatibility notes on both sides only when a configuration template or plugin-installation step changes; never commit runtime data across repositories.

The companion configuration repository is [astrbot_config_himeko](https://github.com/fushuyiliu/astrbot_config_himeko). Both repositories are currently reviewed as private candidates; the link will be generally accessible only after each repository is separately approved for public release. Do not substitute an unreviewed third-party mirror.

### 3. Configure owner and switches

Open “Plugins → Himeko Companion → Plugin configuration” in the AstrBot WebUI:

1. Set `owner_id` to the message platform's **exact sender ID**. Do not use a nickname, phone number, password, or token.
2. Optionally set `platform_id` to accept the owner only on one AstrBot platform; leave it blank to allow the same exact ID in private chats across platforms.
3. Enable `enable_character_prompt`, `enable_memory`, `enable_reminders`, and `enable_attachments` only when wanted.
4. Save and reload the plugin if AstrBot requests it.

All switches start disabled. This is an intentional privacy default, not an installation error.

### 4. Complete one interaction

Send a normal private message as the configured owner. If the interaction prompt is enabled, the current AstrBot model receives that general prompt. If there is no reply, first check AstrBot's platform, model, and trigger settings.

All examples below are fictional:

```text
/记住 Preference I organize reading notes at night
/记忆
/提醒 2026-10-07 20:00 Organize one page of reading notes
```

## Memory, reminders, and attachments

### Memory

- `/记住 topic fact`: create or update a memory.
- `/记忆`: list the current owner's memories.
- `/忘记 topic`: delete one memory.
- `/清空记忆 确认`: delete all plugin memories.

Memory is visible only to the same platform name, platform configuration, and owner ID combination. It is temporary, correctable context—not an instruction—and is never automatically written to an external document.

### Reminders

- `/提醒 YYYY-MM-DD HH:MM item`
- `/提醒列表`
- `/完成提醒 id`
- `/稍后提醒 id minutes`
- `/取消提醒 id`

Times are parsed as UTC+8. Delivery is not guaranteed while the bot is offline. After a restart, the owner must send a new private message to refresh the safe delivery context.

### Attachment Q&A

Send a supported attachment in the owner's private chat, then send a question, or use:

```text
读取 attachment-id What are the three takeaways in this fictional report?
确认读取 attachment-id
```

For PDFs, `确认读取 attachment-id 1-3,5` selects pages. A scanned PDF prompts for local OCR. OCR is not installed by default; install it only when needed, in the **same Python environment that runs AstrBot**:

```powershell
pip install -r requirements-ocr.txt
```

Use `/附件记录` to see Q&A indexes and `/删除附件记录 id` to delete the plugin's saved record. This does not automatically erase AstrBot history, message-platform copies, backups, or model-provider records.

## Data and privacy

Plugin data lives at:

```text
AstrBot/data/plugin_data/astrbot_plugin_himeko/
├── memory.sqlite3
├── reminders/
└── attachments/
    └── 附件问答/
        ├── 临时/
        ├── 记录/
        └── ocr-models/        # appears only after OCR is used
```

Data flow:

1. Normal messages are handled by AstrBot according to your platform and model settings.
2. With memory enabled, only saved concise facts are included as temporary context for the current owner's request.
3. With attachments enabled, the file is parsed locally first; **after confirmation**, extracted text, file information, and your question are sent to the current AstrBot model.
4. Reminder text and memory remain in the local plugin directory. Original attachments are not retained as long-term records; Q&A records remain until you delete them or delete the plugin data.

Model services, AstrBot, and message platforms can keep their own logs or message history. Configure and delete those independently using their documentation. Do not send secrets, payment information, identity numbers, or other people's data without authorization to any model service.

To fully erase this plugin's data, stop AstrBot and delete the `astrbot_plugin_himeko` data directory above. Uninstalling the plugin does not remove data automatically, to prevent accidental loss.

## Verified environment and limitations

- The plugin entry has been imported against Python 3.12 and AstrBot 4.28.1, with eight unit tests. A full message-platform installation acceptance test in an independent AstrBot instance is still outstanding.
- It makes no performance promise for latency, OCR accuracy, reminder timing, or model output correctness.
- Attachments are limited to 20 MB. Legacy `.doc`, archives, and executable files are unsupported.
- Only the owner's private-chat scenario is in scope for v1. Group chat, multi-user isolation, and cross-platform same-ID merging are not included.
- “Delete” covers only data controlled by this plugin; data already received by third parties must be handled in those services.

Common issues:

- **A feature does nothing:** verify the exact `owner_id`, private-chat context, feature switch, and plugin reload.
- **Plugin does not load:** check the AstrBot version, `requirements.txt` install log, and the failed-plugin panel in WebUI.
- **OCR dependency is missing:** install `requirements-ocr.txt` in AstrBot's Python environment or choose “skip OCR.”
- **A reminder was not delivered:** after a restart the owner may not yet have sent a new private message, the conversation may have expired, or the platform may have rejected sending; the reminder fails closed.

## Uninstall

1. Stop or disable the plugin in AstrBot.
2. Remove `AstrBot/data/plugins/astrbot_plugin_himeko/`.
3. Remove `AstrBot/data/plugin_data/astrbot_plugin_himeko/` only after confirming the data is no longer needed.
4. If OCR dependencies were installed, remove them from AstrBot's Python environment according to your package-management policy.

## Development, tests, and contributions

```powershell
python -m pytest
ruff check .
python tools/audit_public_release.py .
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) before contributing. Report security issues privately as described in [SECURITY.md](SECURITY.md); never paste secrets or private chat content into a public issue.

## License and notices

Original code is available under the [MIT License](LICENSE). See [NOTICE.md](NOTICE.md) for upstream relationships, runtime dependencies, and asset boundaries.
