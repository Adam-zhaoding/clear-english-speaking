/**
 * The build engine reports machine-readable codes so the pipeline can stay
 * strict. A first-time user should never see one of those codes, so every
 * known failure is translated into a cause plus the next thing to try.
 */
const messages: Record<string, { reason: string; next: string }> = {
  non_official_bbc_page: { reason: "这个网址不是 BBC Learning English 的官方节目页。", next: "让备课助手换一集官方 6 Minute English。" },
  bbc_page_not_found: { reason: "这一集的 BBC 页面已经打不开了（404）。", next: "让备课助手换一集。" },
  bbc_page_unreachable: { reason: "连不上 BBC 官网。", next: "检查网络或代理后重试。" },
  download_failed: { reason: "从 BBC 下载素材时连接中断。", next: "检查网络后点“重试”。" },
  build_cancelled: { reason: "备课被中止了。", next: "重新点一次备课。" },
  unexpected_engine_error: { reason: "课程引擎遇到了未预料的问题。", next: "点“重试”；若反复出现，请换一集或反馈这条提示。" },
  official_mp3_missing: { reason: "这一集的官方页面上没有找到可用的音频。", next: "换一集试试；不要手工猜测音频地址。" },
  official_transcript_missing: { reason: "这一集没有可确认的官方文稿 PDF（练习册 worksheet 不算）。", next: "换一集试试。" },
  official_transcript_unreadable: { reason: "官方文稿 PDF 下载后无法读取文字。", next: "稍后重试；若持续失败请换一集。" },
  sentence_not_in_official_transcript: { reason: "备课助手挑的句子和官方文稿对不上，可能是它自己改写了原句。", next: "点“重新备课”，让助手严格照抄官方原文。" },
  invalid_sentence_count: { reason: "这节课的重点句不是 5–6 句。", next: "点“重新备课”。" },
  invalid_sentence_timing: { reason: "句子时间轴重叠或超出音频长度。", next: "点“重新备课”；不要手工修改时间。" },
  sentence_alignment_failed: { reason: "有句子没能在音频里定位到（可能音频与文稿版本不一致）。", next: "点“重新备课”，或换一集。" },
  audio_duration_unavailable: { reason: "下载到的音频文件损坏，读不出时长。", next: "检查网络后重试。" },
  downloaded_file_empty: { reason: "从 BBC 下载的文件是空的。", next: "检查网络后重试。" },
  whisper_dependency_unavailable: { reason: "本机语音对齐组件缺失。", next: "重新安装 Clear English Speaking。" },
  whisper_model_unavailable: { reason: "语音识别模型下载失败。", next: "确认能正常联网后重试；首次需要下载约 500MB。" },
  whisper_words_missing: { reason: "语音识别没有从音频里得到任何词。", next: "换一集试试。" },
  external_draft_invalid: { reason: "备课助手写出的草案格式不对。", next: "回到备课中心点“重新备课”，把任务重新发送一次给助手。" },
  model_configuration_missing: { reason: "还没有填写可用的模型服务地址、模型名和 Key。", next: "在“我的 API”里补齐配置后再试。" },
  model_generation_failed: { reason: "你配置的模型服务没有返回合法结果。", next: "检查服务地址、模型名和额度后重试。" },
  model_sentences_missing: { reason: "模型没有返回重点句。", next: "重试一次，或换用 WorkBuddy 备课。" },
  no_eligible_episode: { reason: "没有找到还没学过、且素材齐全的新一集。", next: "过几天 BBC 更新后再试。" },
  episode_id_missing: { reason: "无法从网址识别这一集的编号。", next: "让助手换一集官方节目页。" }
};

/** Turn engine output into one sentence a beginner can act on. */
export function explainBuildError(raw: unknown): string {
  const text = raw instanceof Error ? raw.message : String(raw ?? "");
  const trimmed = text.trim();
  if (!trimmed) return "备课失败，原因未知。你已有的课程没有受影响。";
  const code = Object.keys(messages).find((key) => trimmed.includes(key));
  if (!code) return `${trimmed}\n你已有的课程没有受影响。`;
  return `${messages[code].reason}\n下一步：${messages[code].next}`;
}

export const buildErrorCodes = messages;
