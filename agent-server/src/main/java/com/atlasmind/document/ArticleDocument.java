package com.atlasmind.document;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.Id;
import org.springframework.data.elasticsearch.annotations.*;

import java.time.LocalDateTime;

/**
 * Elasticsearch 文章索引文档。
 * <p>
 * 索引名 {@code agent_contents}，仅索引已发布(status=1)的文章。
 * 使用 IK 分词器处理中文搜索。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Document(indexName = "agent_contents")
@Setting(settingPath = "elasticsearch/settings.json")
public class ArticleDocument {

    @Id
    private Long id;

    @MultiField(
        mainField = @Field(type = FieldType.Text, analyzer = "ik_max_word", searchAnalyzer = "ik_smart"),
        otherFields = {
            @InnerField(suffix = "keyword", type = FieldType.Keyword)
        }
    )
    private String title;

    @Field(type = FieldType.Text, analyzer = "ik_max_word", searchAnalyzer = "ik_smart")
    private String content;

    @Field(type = FieldType.Text, analyzer = "ik_max_word", searchAnalyzer = "ik_smart")
    private String summary;

    @Field(type = FieldType.Long)
    private Long categoryId;

    @Field(type = FieldType.Integer)
    private Integer status;

    /** 可见性：PUBLIC / RAG_ONLY / PRIVATE */
    @Field(type = FieldType.Keyword)
    private String visibility;

    /**
     * 文章语义向量（默认 Qwen3-Embedding-4B 为 2560 维，cosine 相似度）。
     * 索引时调用 embedding API 生成，用于 kNN 语义搜索。
     */
    @Field(type = FieldType.Dense_Vector, dims = 2560)
    private float[] embedding;

    @Field(type = FieldType.Date, format = DateFormat.date_hour_minute_second)
    private LocalDateTime createTime;
}
