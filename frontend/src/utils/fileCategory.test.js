import { describe, expect, it } from 'vitest'
import { categoryOf, fileVisual, iconColor, iconName } from './fileCategory'

describe('categoryOf', () => {
  it('识别图片后缀（大小写不敏感）', () => {
    expect(categoryOf('jpg')).toBe('image')
    expect(categoryOf('PNG')).toBe('image')
    expect(categoryOf('WebP')).toBe('image')
  })

  it('识别视频/音频/压缩包', () => {
    expect(categoryOf('mp4')).toBe('video')
    expect(categoryOf('flac')).toBe('audio')
    expect(categoryOf('7z')).toBe('archive')
  })

  it('办公文档细分为 word/sheet/slide/pdf', () => {
    expect(categoryOf('doc')).toBe('word')
    expect(categoryOf('docx')).toBe('word')
    expect(categoryOf('xls')).toBe('sheet')
    expect(categoryOf('xlsx')).toBe('sheet')
    expect(categoryOf('ppt')).toBe('slide')
    expect(categoryOf('pptx')).toBe('slide')
    expect(categoryOf('pdf')).toBe('pdf')
    expect(categoryOf('txt')).toBe('text')
    expect(categoryOf('md')).toBe('markdown')
  })

  it('未知后缀与空值归为 other', () => {
    expect(categoryOf('xyz')).toBe('other')
    expect(categoryOf('')).toBe('other')
    expect(categoryOf(null)).toBe('other')
    expect(categoryOf(undefined)).toBe('other')
  })
})

describe('iconName', () => {
  it('文件夹固定返回 Folder', () => {
    expect(iconName({ is_folder: true, file_suffix: '' })).toBe('Folder')
  })

  it('按分类返回对应图标，未知类型回退 Document', () => {
    expect(iconName({ is_folder: false, file_suffix: 'png' })).toBe('Picture')
    expect(iconName({ is_folder: false, file_suffix: 'zip' })).toBe('Files')
    expect(iconName({ is_folder: false, file_suffix: 'pdf' })).toBe('Document')
    expect(iconName({ is_folder: false, file_suffix: 'zzz' })).toBe('Document')
  })
})

describe('iconColor', () => {
  it('文件夹为琥珀色，图片为绿色，未知为蓝色（旧粗分类兼容）', () => {
    expect(iconColor({ is_folder: true })).toBe('#f59e0b')
    expect(iconColor({ is_folder: false, file_suffix: 'jpg' })).toBe('#10b981')
    expect(iconColor({ is_folder: false, file_suffix: 'qqq' })).toBe('#3b82f6')
  })
})

describe('fileVisual', () => {
  it('文件夹返回黄色且无标签', () => {
    const v = fileVisual({ is_folder: true })
    expect(v.folder).toBe(true)
    expect(v.color).toBe('#f59e0b')
    expect(v.label).toBe('')
  })

  it('常见后缀给出独立颜色与大写标签（0 配额等无关字段不受影响）', () => {
    expect(fileVisual({ file_suffix: 'pdf' })).toMatchObject({ color: '#d93025', label: 'PDF' })
    expect(fileVisual({ file_suffix: 'docx' })).toMatchObject({ color: '#2b7cd3', label: 'DOCX' })
    expect(fileVisual({ file_suffix: 'xlsx' })).toMatchObject({ color: '#21a366', label: 'XLSX' })
    expect(fileVisual({ file_suffix: 'pptx' })).toMatchObject({ color: '#ea580c', label: 'PPTX' })
    expect(fileVisual({ file_suffix: 'txt' })).toMatchObject({ label: 'TXT' })
    expect(fileVisual({ file_suffix: 'md' })).toMatchObject({ label: 'MD' })
    expect(fileVisual({ file_suffix: 'png' })).toMatchObject({ label: 'PNG' })
    expect(fileVisual({ file_suffix: 'mp4' })).toMatchObject({ label: 'MP4' })
  })

  it('后缀缺失时从文件名推断；无后缀文件使用默认灰色', () => {
    expect(fileVisual({ file_name: 'report.PDF' }).label).toBe('PDF')
    expect(fileVisual({ file_name: 'README.md' }).color).toBe('#4f46e5')
    const v = fileVisual({ file_name: 'noext' })
    expect(v.color).toBe('#94a3b8')
    expect(v.label).toBe('')
  })

  it('超过 4 个字符的标签截断为 4 位', () => {
    expect(fileVisual({ file_suffix: 'numbers' }).label).toBe('NUMB')
  })
})
