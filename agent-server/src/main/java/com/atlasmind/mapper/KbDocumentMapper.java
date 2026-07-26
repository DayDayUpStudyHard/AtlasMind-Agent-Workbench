package com.atlasmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.atlasmind.entity.KbDocument;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface KbDocumentMapper extends BaseMapper<KbDocument> {
    @Delete("DELETE FROM kb_document WHERE id = #{id}")
    int hardDeleteById(Long id);
}
