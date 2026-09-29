# SPDX-License-Identifier: AGPL-3.0-only
"""Every Stash GraphQL document the backend uses, checked against Stash v0.31.1.

The only writes are the ones reference spec §5 allows: marker create/update, image tag ADD/REMOVE and
creating the two workflow tags. Playback fields (sceneStreams) are gone: the UI plays Stash URLs itself.
"""

VERSION = """
query Version { version { version } }
"""

FIND_TAGS_BY_NAME = """
query FindTagsByName($q: String!) {
  findTags(filter: { q: $q, per_page: 25, sort: "name", direction: ASC }) {
    tags { id name }
  }
}
"""

# Stash's EQUALS is SQL LIKE: case-insensitive, and "%" and "_" act as wildcards. The caller re-checks
# the name exactly (ignoring case). A tag whose alias matches counts too: Stash won't create a tag whose
# name is another tag's alias.
FIND_TAG_EXACT = """
query FindTagExact($name: String!) {
  findTags(
    tag_filter: { name: { value: $name, modifier: EQUALS }, OR: { aliases: { value: $name, modifier: EQUALS } } }
    filter: { per_page: -1 }
  ) {
    tags { id name aliases }
  }
}
"""

TAG_CREATE = """
mutation TagCreate($name: String!) { tagCreate(input: { name: $name }) { id name } }
"""

SCENE_FIELDS = """
  id title date created_at
  files { path duration width height frame_rate video_codec audio_codec format size }
  paths { stream screenshot }
  tags { id name }
  performers { name }
  studio { name }
"""

MARKER_FIELDS = (
    """
  id title seconds end_seconds screenshot preview created_at updated_at
  primary_tag { id name }
  tags { id name }
  scene { """
    + SCENE_FIELDS
    + """ }
"""
)

FIND_QUEUED_MARKERS = (
    """
query QueuedMarkers($tagId: ID!, $page: Int!, $perPage: Int!) {
  findSceneMarkers(
    scene_marker_filter: { tags: { value: [$tagId], modifier: INCLUDES } }
    filter: { page: $page, per_page: $perPage, sort: "created_at", direction: DESC }
  ) {
    count
    scene_markers { """
    + MARKER_FIELDS
    + """ }
  }
}
"""
)

FIND_MARKER_BY_ID = (
    """
query MarkerById($id: ID!) {
  findSceneMarkers(ids: [$id], filter: { per_page: 1 }) {
    scene_markers { """
    + MARKER_FIELDS
    + """ }
  }
}
"""
)

MARKER_CREATE = """
mutation MarkerCreate($scene_id: ID!, $title: String!, $seconds: Float!, $end_seconds: Float,
                      $primary_tag_id: ID!, $tag_ids: [ID!]) {
  sceneMarkerCreate(input: {
    scene_id: $scene_id, title: $title, seconds: $seconds, end_seconds: $end_seconds,
    primary_tag_id: $primary_tag_id, tag_ids: $tag_ids
  }) { id }
}
"""

MARKER_UPDATE = """
mutation MarkerUpdate($id: ID!, $seconds: Float, $end_seconds: Float, $primary_tag_id: ID, $tag_ids: [ID!]) {
  sceneMarkerUpdate(input: {
    id: $id, seconds: $seconds, end_seconds: $end_seconds, primary_tag_id: $primary_tag_id, tag_ids: $tag_ids
  }) { id seconds end_seconds primary_tag { id name } tags { id name } }
}
"""

IMAGE_FIELDS = """
  id title date created_at updated_at
  paths { thumbnail image }
  visual_files {
    __typename
    ... on ImageFile { path width height size format zip_file { path } }
    ... on VideoFile { path width height size duration frame_rate video_codec format zip_file { path } }
  }
  tags { id name }
  performers { name }
  studio { name }
  galleries { id title tags { id name } }
"""

FIND_QUEUED_IMAGES = (
    """
query QueuedImages($tagId: ID!, $page: Int!, $perPage: Int!) {
  findImages(
    image_filter: { tags: { value: [$tagId], modifier: INCLUDES } }
    filter: { page: $page, per_page: $perPage, sort: "created_at", direction: DESC }
  ) {
    count
    images { """
    + IMAGE_FIELDS
    + """ }
  }
}
"""
)

FIND_IMAGE_BY_ID = (
    """
query ImageById($id: ID!) {
  findImage(id: $id) { """
    + IMAGE_FIELDS
    + """ }
}
"""
)

BULK_IMAGE_ADD_TAGS = """
mutation BulkImageAddTags($ids: [ID!]!, $add: [ID!]) {
  bulkImageUpdate(input: { ids: $ids, tag_ids: { ids: $add, mode: ADD } }) { id }
}
"""

BULK_IMAGE_REMOVE_TAGS = """
mutation BulkImageRemoveTags($ids: [ID!]!, $remove: [ID!]) {
  bulkImageUpdate(input: { ids: $ids, tag_ids: { ids: $remove, mode: REMOVE } }) { id }
}
"""

FIND_SCENES = (
    """
query FindScenes($q: String!, $page: Int!, $perPage: Int!) {
  findScenes(filter: { q: $q, page: $page, per_page: $perPage, sort: "updated_at", direction: DESC }) {
    count
    scenes { """
    + SCENE_FIELDS
    + """ }
  }
}
"""
)

FIND_SCENE_BY_ID = (
    """
query SceneById($id: ID!) {
  findScene(id: $id) { """
    + SCENE_FIELDS
    + """ }
}
"""
)
