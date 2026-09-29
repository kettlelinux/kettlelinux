/* V4L2's stateful AV1 format, which iris decodes on SM8550 but the build chroot's
 * linux-api-headers (6.18) lack; same definition as the kernel's (7.2) videodev2.h. */
#define V4L2_PIX_FMT_AV1 v4l2_fourcc('A', 'V', '0', '1')
