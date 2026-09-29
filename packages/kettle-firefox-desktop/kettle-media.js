// Kettle Linux defaults (kettle-firefox-desktop). Defaults, not locks: about:config can change them.

// AV1 off, so sites that offer VP9 too (YouTube) send VP9, which the Thor's video decoder (iris)
// decodes in hardware; its AV1 decoding shows no picture in Firefox (see packages/ffmpeg-v4l2).
pref("media.av1.enabled", false);
