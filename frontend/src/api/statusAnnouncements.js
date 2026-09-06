import api from './client'

// Cap v2, 5b — status page announcements, nested under the owning group.
export const statusAnnouncementsApi = {
  list: (groupId, config = {}) => api.get(`/groups/${groupId}/announcements`, config),
  create: (groupId, data, config = {}) =>
    api.post(`/groups/${groupId}/announcements`, data, config),
  updateTitle: (groupId, announcementId, title, config = {}) =>
    api.patch(`/groups/${groupId}/announcements/${announcementId}`, { title }, config),
  addUpdate: (groupId, announcementId, data, config = {}) =>
    api.post(`/groups/${groupId}/announcements/${announcementId}/updates`, data, config),
  close: (groupId, announcementId, config = {}) =>
    api.post(`/groups/${groupId}/announcements/${announcementId}/close`, undefined, config),
}
