package com.atlasmind.service.impl;

import com.atlasmind.entity.KbNotification;
import com.atlasmind.entity.KbSpace;
import com.atlasmind.gateway.AiGateway;
import com.atlasmind.mapper.KbDocumentChunkMapper;
import com.atlasmind.mapper.KbDocumentMapper;
import com.atlasmind.mapper.KbIngestJobMapper;
import com.atlasmind.mapper.KbNotificationMapper;
import com.atlasmind.mapper.KbSpaceMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeBaseServiceImpl")
class KnowledgeBaseServiceImplTest {

    @Mock
    private KbSpaceMapper spaceMapper;

    @Mock
    private KbDocumentMapper documentMapper;

    @Mock
    private KbDocumentChunkMapper chunkMapper;

    @Mock
    private KbIngestJobMapper jobMapper;

    @Mock
    private KbNotificationMapper notificationMapper;

    @Mock
    private AiGateway aiGateway;

    @InjectMocks
    private KnowledgeBaseServiceImpl service;

    @Test
    @DisplayName("listSpaces returns active spaces")
    void listSpaces() {
        KbSpace space = new KbSpace();
        space.setId(1L);
        space.setName("Project Reference");
        space.setDeleted(0);

        when(spaceMapper.selectList(any())).thenReturn(List.of(space));

        List<KbSpace> result = service.listSpaces();

        assertEquals(1, result.size());
        assertEquals("Project Reference", result.get(0).getName());
        verify(spaceMapper).selectList(any());
    }

    @Test
    @DisplayName("countUnreadNotifications returns mapper count")
    void countUnreadNotifications() {
        when(notificationMapper.selectCount(any())).thenReturn(3L);

        assertEquals(3L, service.countUnreadNotifications());
        verify(notificationMapper).selectCount(any());
    }

    @Test
    @DisplayName("markNotificationRead flips unread flag")
    void markNotificationRead() {
        KbNotification notification = new KbNotification();
        notification.setId(7L);
        notification.setReadStatus(0);
        when(notificationMapper.selectById(7L)).thenReturn(notification);

        service.markNotificationRead(7L);

        assertEquals(1, notification.getReadStatus());
        verify(notificationMapper).updateById(notification);
    }
}
