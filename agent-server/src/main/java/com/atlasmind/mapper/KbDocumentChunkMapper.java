package com.atlasmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.atlasmind.entity.KbDocumentChunk;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface KbDocumentChunkMapper extends BaseMapper<KbDocumentChunk> {
    @Delete("DELETE FROM kb_document_chunk WHERE document_id = #{documentId}")
    int hardDeleteByDocumentId(Long documentId);
}
