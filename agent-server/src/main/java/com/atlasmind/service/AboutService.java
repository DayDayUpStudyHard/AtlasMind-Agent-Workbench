package com.atlasmind.service;

import com.atlasmind.entity.About;

public interface AboutService {
    About get();
    void update(String content, String timeline);
}
