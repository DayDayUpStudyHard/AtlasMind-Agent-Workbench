package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.Moment;
import com.atlasmind.mapper.MomentMapper;
import com.atlasmind.service.MomentService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import java.time.LocalDateTime;

@Service
@RequiredArgsConstructor
public class MomentServiceImpl implements MomentService {

    private final MomentMapper momentMapper;

    @Override
    public Page<Moment> list(int page, int size) {
        return momentMapper.selectPage(new Page<>(page, size),
                new LambdaQueryWrapper<Moment>().orderByDesc(Moment::getCreateTime));
    }

    @Override
    public Moment create(Moment moment) {
        moment.setCreateTime(LocalDateTime.now());
        momentMapper.insert(moment);
        return moment;
    }

    @Override
    public Moment update(Long id, Moment moment) {
        Moment existing = momentMapper.selectById(id);
        if (existing == null) throw new IllegalArgumentException("说说不存在");
        if (moment.getContent() != null) existing.setContent(moment.getContent());
        if (moment.getImage() != null) existing.setImage(moment.getImage());
        momentMapper.updateById(existing);
        return existing;
    }

    @Override
    public void delete(Long id) {
        momentMapper.deleteById(id);
    }
}
