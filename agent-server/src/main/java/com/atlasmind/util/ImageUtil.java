package com.atlasmind.util;

import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.ImageWriter;
import javax.imageio.stream.ImageOutputStream;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.Iterator;
import java.util.Set;

/**
 * 图片压缩与缩略图工具，纯 JDK 实现（javax.imageio + java.awt），零外部依赖。
 * <p>
 * 支持 JPEG/PNG/BMP 的压缩和缩略图生成。GIF 动图跳过压缩（防动画丢失），
 * 但会生成静态缩略图。WebP 等不支持格式静默跳过。
 * <p>
 * 在 Docker 容器中需确保已设置 {@code java.awt.headless=true}（Spring Boot 默认设置）。
 */
public final class ImageUtil {

    private static final Set<String> SUPPORTED_FORMATS = Set.of("jpg", "jpeg", "png", "bmp", "gif");

    /** 超过此宽度才压缩（像素） */
    private static final int MAX_WIDTH = 1920;
    /** 超过此高度才压缩（像素） */
    private static final int MAX_HEIGHT = 1920;
    /** 缩略图目标宽度 */
    private static final int THUMB_WIDTH = 400;
    /** JPEG 输出质量 0-1 */
    private static final float QUALITY = 0.80f;

    private ImageUtil() {}

    // ═══════════════════════════════════════════
    // 公共方法
    // ═══════════════════════════════════════════

    /** 根据文件名后缀判断是否为可处理的图片 */
    public static boolean isImage(String filename) {
        if (filename == null) return false;
        int dot = filename.lastIndexOf('.');
        if (dot < 0) return false;
        return SUPPORTED_FORMATS.contains(filename.substring(dot + 1).toLowerCase());
    }

    /** 获取文件名后缀（不含点，小写），用于 ImageIO writer 查找 */
    public static String format(String filename) {
        if (filename == null) return "jpg";
        int dot = filename.lastIndexOf('.');
        if (dot < 0) return "jpg";
        String ext = filename.substring(dot + 1).toLowerCase();
        return switch (ext) {
            case "jpeg", "jpg" -> "jpg";
            case "png" -> "png";
            case "gif" -> "gif";
            case "bmp" -> "bmp";
            default -> ext;
        };
    }

    /**
     * 等比例缩放图片（超过阈值才缩小），返回压缩后的字节数组。
     * GIF 动图直接返回原始字节（不压缩，防止动画丢失）。
     *
     * @param input  原始图片字节
     * @param format 输出格式（jpg/png/bmp）
     * @return 压缩后字节（无需压缩时返回原始字节）
     */
    public static byte[] compress(byte[] input, String format) {
        try {
            BufferedImage src = ImageIO.read(new ByteArrayInputStream(input));
            if (src == null) return input; // 无法解码，保留原始

            int w = src.getWidth();
            int h = src.getHeight();

            // 已小于阈值，不缩放（但 JPEG 仍做轻微压缩优化）
            if (w <= MAX_WIDTH && h <= MAX_HEIGHT) {
                if ("gif".equals(format)) return input;    // 动图不处理
                return encode(src, format);
            }

            // 计算等比缩放尺寸
            double ratio = Math.min((double) MAX_WIDTH / w, (double) MAX_HEIGHT / h);
            int newW = (int) (w * ratio);
            int newH = (int) (h * ratio);

            BufferedImage scaled = scaleLanczos(src, newW, newH);
            src.flush();
            return encode(scaled, format);
        } catch (Exception e) {
            return input; // 压缩失败，静默回退原始
        }
    }

    /**
     * 生成缩略图（等比例缩放至目标宽度）。
     * GIF 取第一帧。
     *
     * @param input  原始图片字节
     * @param format 输出格式
     * @return 缩略图字节
     */
    public static byte[] thumbnail(byte[] input, String format) {
        try {
            BufferedImage src = ImageIO.read(new ByteArrayInputStream(input));
            if (src == null) return input;

            int w = src.getWidth();
            int h = src.getHeight();

            // 原图比缩略图还小，直接返回原图编码
            if (w <= THUMB_WIDTH) {
                return encode(src, format);
            }

            double ratio = (double) THUMB_WIDTH / w;
            int newH = (int) (h * ratio);

            BufferedImage scaled = scaleLanczos(src, THUMB_WIDTH, newH);
            src.flush();
            return encode(scaled, format);
        } catch (Exception e) {
            return input;
        }
    }

    // ═══════════════════════════════════════════
    // 内部方法
    // ═══════════════════════════════════════════

    /** 高质量缩放（Lanczos 近似：双三次 + 渲染提示） */
    private static BufferedImage scaleLanczos(BufferedImage src, int w, int h) {
        // 带透明通道的用 ARGB，否则用 RGB（减小文件体积）
        boolean hasAlpha = src.getColorModel().hasAlpha();
        int type = hasAlpha ? BufferedImage.TYPE_INT_ARGB : BufferedImage.TYPE_INT_RGB;

        BufferedImage dest = new BufferedImage(w, h, type);
        Graphics2D g2d = dest.createGraphics();
        g2d.setRenderingHint(RenderingHints.KEY_INTERPOLATION,
                RenderingHints.VALUE_INTERPOLATION_BICUBIC);
        g2d.setRenderingHint(RenderingHints.KEY_RENDERING,
                RenderingHints.VALUE_RENDER_QUALITY);
        g2d.setRenderingHint(RenderingHints.KEY_ANTIALIASING,
                RenderingHints.VALUE_ANTIALIAS_ON);
        g2d.drawImage(src, 0, 0, w, h, null);
        g2d.dispose();
        return dest;
    }

    /** 编码 BufferedImage → byte[]，JPEG 使用 Quality 参数压缩 */
    private static byte[] encode(BufferedImage image, String format) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();

        if ("jpg".equals(format) || "jpeg".equals(format)) {
            // JPEG 使用 Quality 参数压缩
            Iterator<ImageWriter> writers = ImageIO.getImageWritersByFormatName("jpeg");
            if (writers.hasNext()) {
                ImageWriter writer = writers.next();
                try (ImageOutputStream ios = ImageIO.createImageOutputStream(out)) {
                    writer.setOutput(ios);
                    ImageWriteParam param = writer.getDefaultWriteParam();
                    param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
                    param.setCompressionQuality(QUALITY);
                    writer.write(null, new IIOImage(image, null, null), param);
                } finally {
                    writer.dispose();
                }
                return out.toByteArray();
            }
        }

        // PNG/BMP/GIF 等直接写出（ImageIO 处理自己的压缩）
        ImageIO.write(image, format, out);
        image.flush();
        return out.toByteArray();
    }
}
