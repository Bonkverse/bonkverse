// Bonkverse Skin Editor - Enhanced Version with Konva.js
// Setup the main Konva stage and layer
const stage = new Konva.Stage({
    container: 'editor',
    width: 500,
    height: 500
});

// Create circular clip to make the editor round
const clipCircle = new Konva.Circle({
    x: stage.width() / 2,
    y: stage.height() / 2,
    radius: stage.width() / 2,
});

const layer = new Konva.Layer({
    clip: clipCircle
});
stage.add(layer);

// Track the currently selected shape
let selectedShape = null;
let activeMode = 'move'; // 'move', 'rotate', or 'resize'

// Undo/redo stack
let history = [];
let historyStep = -1;
const maxHistorySteps = 30;

// Initialize color picker
const colorPicker = new iro.ColorPicker('#colorPicker', {
    width: 200,
    color: "#00c3ff",
    borderWidth: 1,
    borderColor: "#243041",
});

// Initialize layer tracking
const layers = [];
let activeLayerId = null;

// Save stage state to history
function saveHistory() {
    history = history.slice(0, historyStep + 1);
    history.push(layer.toJSON());
    historyStep++;
    
    // Limit history size
    if (history.length > maxHistorySteps) {
        history.shift();
        historyStep--;
    }
    
    // Update UI buttons based on history state
    document.getElementById('undoBtn').disabled = historyStep <= 0;
    document.getElementById('redoBtn').disabled = historyStep >= history.length - 1;
    
    // Auto-save to localStorage
    localStorage.setItem('bonkverseSkinEditor', layer.toJSON());
}

// File upload handler
const fileInput = document.getElementById('fileInput');
const preview = document.getElementById('preview');
fileInput.addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (!file) return;
    const ext = file.name.split('.').pop().toLowerCase();
    
    // Clear the layer list before adding new content
    document.getElementById('layerList').innerHTML = '';
    if (ext !== 'png' && ext !== 'svg') {
        alert('Only PNG or SVG files allowed!');
        return;
    }
    
    // Reset canvas
    layer.destroyChildren();
    preview.innerHTML = '';
    
    const reader = new FileReader();
    reader.onload = function(evt) {
        if (ext === 'png') {
            const img = new window.Image();
            img.src = evt.target.result;
            img.onload = function() {
                // Add preview
                const previewImg = document.createElement('img');
                previewImg.src = evt.target.result;
                previewImg.style.maxWidth = '100%';
                previewImg.style.maxHeight = '100%';
                preview.appendChild(previewImg);
                
                // Clear existing layers and create new background
                layer.destroyChildren();
                
                // Create background circle
                const background = new Konva.Circle({
                    x: stage.width() / 2,
                    y: stage.height() / 2,
                    radius: stage.width() / 2 - 5,
                    fill: '#222222',
                    id: 'skinBackground',
                    name: 'skin-background',
                    draggable: false,
                });
                layer.add(background);
                addToLayerList('Background', background._id);
                
                // Calculate position to center the image
                const centerX = stage.width() / 2;
                const centerY = stage.height() / 2;
                
                // Calculate scale to fit the image within the circle
                const maxDimension = Math.min(stage.width(), stage.height()) * 0.9;
                const scaleX = maxDimension / img.width;
                const scaleY = maxDimension / img.height;
                const scale = Math.min(scaleX, scaleY);
                
                // Create Konva image with clipping
                const konvaImg = new Konva.Image({
                    id: 'mainSkin',
                    image: img,
                    x: centerX - (img.width * scale / 2),
                    y: centerY - (img.height * scale / 2),
                    width: img.width * scale,
                    height: img.height * scale,
                    draggable: true,
                    name: 'skin-layer'
                });
                
                // Add transformer for the image
                addTransformerToShape(konvaImg);
                
                // Add to layer and track
                layer.add(konvaImg);
                addToLayerList('Skin Image', konvaImg._id);
                
                // Set as selected shape
                selectShape(konvaImg);
                
                layer.draw();
                saveHistory();
            };
        } else if (ext === 'svg') {
            // SVG handling
            try {
                // Set SVG preview
                const previewDiv = document.createElement('div');
                previewDiv.innerHTML = '<div style="padding:10px;font-size:12px;color:#aaa;">SVG Preview</div>';
                preview.appendChild(previewDiv);
                
                // Create an image object for the SVG
                const svgImage = new Image();
                svgImage.src = evt.target.result;
                svgImage.onload = function() {
                    // Add the SVG to the preview
                    const svgPreview = document.createElement('img');
                    svgPreview.src = evt.target.result;
                    svgPreview.style.maxWidth = '100%';
                    svgPreview.style.maxHeight = '100px';
                    preview.appendChild(svgPreview);
                    
                // Clear existing layers and create new background
                layer.destroyChildren();
                document.getElementById('layerList').innerHTML = '';
                
                // Create background circle
                const background = new Konva.Circle({
                    x: stage.width() / 2,
                    y: stage.height() / 2,
                    radius: stage.width() / 2 - 5,
                    fill: '#222222',
                    id: 'skinBackground',
                    name: 'skin-background',
                    draggable: false,
                });
                layer.add(background);
                addToLayerList('Background', background._id);
                
                // Center coordinates
                const centerX = stage.width() / 2;
                const centerY = stage.height() / 2;
                
                // Size for SVG (80% of the stage width to fit within the circle)
                const svgSize = stage.width() * 0.8;
                
                // Create Konva image and add to layer
                const konvaImg = new Konva.Image({
                    id: 'mainSkin',
                    image: svgImage,
                    x: centerX - (svgSize / 2),
                    y: centerY - (svgSize / 2),
                    width: svgSize,
                    height: svgSize,
                    draggable: true,
                    name: 'skin-layer'
                });                    // Add transformer for the image
                    addTransformerToShape(konvaImg);
                    
                    // Add to layer and track
                    layer.add(konvaImg);
                    addToLayerList('Skin SVG', konvaImg._id);
                    
                    // Set as selected shape
                    selectShape(konvaImg);
                    
                    layer.draw();
                    saveHistory();
                };
                
                svgImage.onerror = function() {
                    alert('Error loading SVG file. Please try a different file.');
                };
            } catch (err) {
                console.error('SVG load error:', err);
                alert('Error processing SVG file: ' + err.message);
            }
        }
    };
    reader.readAsDataURL(file);
});

// Helper function to add transformer to shape
function addTransformerToShape(shape) {
    // Remove existing transformer
    stage.find('Transformer').destroy();
    
    // Create new transformer
    const tr = new Konva.Transformer({
        nodes: [shape],
        keepRatio: false,
        rotateEnabled: true,
        enabledAnchors: ['top-left', 'top-right', 'bottom-left', 'bottom-right'],
        boundBoxFunc: function(oldBox, newBox) {
            // Limit resize to stage bounds
            if (newBox.width < 10 || newBox.height < 10) {
                return oldBox;
            }
            return newBox;
        },
    });
    
    layer.add(tr);
}

// Function to select a shape
function selectShape(shape) {
    // Deselect previous shape
    if (selectedShape) {
        selectedShape.stroke(null);
    }
    
    selectedShape = shape;
    
    if (shape) {
        // Add transformer to selected shape
        addTransformerToShape(shape);
        
        // Highlight in layer list
        const layerItems = document.querySelectorAll('.layer-item');
        layerItems.forEach(item => {
            if (item.dataset.id === shape._id) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
    }
    
    layer.draw();
}

// Function to add shape to layer list
function addToLayerList(name, id) {
    const layerList = document.getElementById('layerList');
    const layerItem = document.createElement('div');
    layerItem.className = 'layer-item';
    layerItem.dataset.id = id;
    layerItem.textContent = name;
    
    layerItem.addEventListener('click', () => {
        const shape = layer.findOne('#' + id);
        if (shape) {
            selectShape(shape);
        }
    });
    
    layerList.appendChild(layerItem);
    
    // Add to layers array
    layers.push({
        id: id,
        name: name
    });
}

// Add event listeners for tool buttons
document.getElementById('moveBtn').addEventListener('click', () => {
    activeMode = 'move';
    document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById('moveBtn').classList.add('active');
});

document.getElementById('rotateBtn').addEventListener('click', () => {
    activeMode = 'rotate';
    document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById('rotateBtn').classList.add('active');
});

document.getElementById('resizeBtn').addEventListener('click', () => {
    activeMode = 'resize';
    document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById('resizeBtn').classList.add('active');
});

// Color picker event
colorPicker.on('color:change', (color) => {
    if (selectedShape) {
        selectedShape.fill(color.hexString);
        layer.draw();
    }
});

// Undo/Redo buttons
document.getElementById('undoBtn').addEventListener('click', () => {
    if (historyStep > 0) {
        historyStep--;
        const jsonData = history[historyStep];
        layer.destroyChildren();
        
        // Parse the JSON data
        const newLayer = Konva.Node.create(jsonData, 'editor');
        layer.draw();
        
        // Update UI
        document.getElementById('undoBtn').disabled = historyStep <= 0;
        document.getElementById('redoBtn').disabled = false;
    }
});

document.getElementById('redoBtn').addEventListener('click', () => {
    if (historyStep < history.length - 1) {
        historyStep++;
        const jsonData = history[historyStep];
        layer.destroyChildren();
        
        // Parse the JSON data
        const newLayer = Konva.Node.create(jsonData, 'editor');
        layer.draw();
        
        // Update UI
        document.getElementById('redoBtn').disabled = historyStep >= history.length - 1;
        document.getElementById('undoBtn').disabled = false;
    }
});

// Export PNG
const downloadPng = document.getElementById('downloadPng');
downloadPng.addEventListener('click', function() {
    // Hide transformers for export
    const transformers = stage.find('Transformer');
    transformers.forEach(tr => tr.hide());
    layer.draw();
    
    // Export as PNG with proper round clipping
    // The layer already has circular clipping applied
    const dataURL = stage.toDataURL({ 
        pixelRatio: 3, // Higher quality
        mimeType: 'image/png'
    });
    
    // Create download link
    const a = document.createElement('a');
    a.href = dataURL;
    a.download = 'bonkverse_skin.png';
    a.click();
    
    // Show transformers again
    transformers.forEach(tr => tr.show());
    layer.draw();
});

// Save as JSON
const downloadJson = document.getElementById('downloadJson');
downloadJson.addEventListener('click', function() {
    const stageData = {
        version: '1.0',
        stage: stage.toJSON(),
        layerInfo: JSON.stringify(layers)
    };
    
    const json = JSON.stringify(stageData);
    const a = document.createElement('a');
    a.href = 'data:application/json;charset=utf-8,' + encodeURIComponent(json);
    a.download = 'bonkverse_skin_project.json';
    a.click();
});

// Load JSON
const loadJson = document.getElementById('loadJson');
loadJson.addEventListener('click', function() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = function(e) {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = function(evt) {
            try {
                // Clear existing content
                layer.destroyChildren();
                document.getElementById('layerList').innerHTML = '';
                
                // Parse project data
                const projectData = JSON.parse(evt.target.result);
                
                // Load stage data
                const stageData = projectData.stage;
                Konva.Node.create(stageData, 'editor');
                
                // Rebuild layer list if available
                if (projectData.layerInfo) {
                    const layerInfo = JSON.parse(projectData.layerInfo);
                    layerInfo.forEach(info => {
                        addToLayerList(info.name, info.id);
                    });
                }
                
                layer.draw();
                saveHistory();
            } catch (error) {
                console.error('Error loading project:', error);
                alert('Error loading project. File may be corrupted.');
            }
        };
        reader.readAsText(file);
    };
    input.click();
});

// Reset
const resetCanvas = document.getElementById('resetCanvas');
resetCanvas.addEventListener('click', function() {
    if (confirm('Reset the canvas? All unsaved changes will be lost.')) {
        layer.destroyChildren();
        document.getElementById('layerList').innerHTML = '';
        preview.innerHTML = '';
        selectedShape = null;
        layer.draw();
        saveHistory();
    }
});

// Add default round skin background to editor
function addDefaultSkin() {
    // Create basic circular skin shape
    const background = new Konva.Circle({
        x: stage.width() / 2,
        y: stage.height() / 2,
        radius: stage.width() / 2 - 5,
        fill: '#222222',
        id: 'skinBackground',
        name: 'skin-background',
        draggable: false,
    });
    
    const circle = new Konva.Circle({
        x: stage.width() / 2,
        y: stage.height() / 2,
        radius: stage.width() / 4,
        fill: '#00c3ff',
        stroke: '#ffffff',
        strokeWidth: 2,
        id: 'mainCircle',
        name: 'skin-element',
        draggable: true,
    });
    
    // Add elements to layer
    layer.add(background);
    layer.add(circle);
    
    // Add to layer list
    addToLayerList('Background', background._id);
    addToLayerList('Circle', circle._id);
    
    // Set as selected shape
    selectShape(circle);
    
    layer.draw();
    saveHistory();
}

// Add a new shape to the canvas
function addNewShape(shapeType) {
    let shape;
    const centerX = stage.width() / 2;
    const centerY = stage.height() / 2;
    
    if (shapeType === 'circle') {
        shape = new Konva.Circle({
            x: centerX,
            y: centerY,
            radius: 50,
            fill: colorPicker.color.hexString,
            draggable: true,
            name: 'skin-element',
        });
    } else if (shapeType === 'rect') {
        shape = new Konva.Rect({
            x: centerX - 50,
            y: centerY - 50,
            width: 100,
            height: 100,
            fill: colorPicker.color.hexString,
            draggable: true,
            name: 'skin-element',
        });
    } else if (shapeType === 'triangle') {
        shape = new Konva.RegularPolygon({
            x: centerX,
            y: centerY,
            sides: 3,
            radius: 50,
            fill: colorPicker.color.hexString,
            draggable: true,
            name: 'skin-element',
        });
    }
    
    if (shape) {
        layer.add(shape);
        addToLayerList(shapeType.charAt(0).toUpperCase() + shapeType.slice(1), shape._id);
        selectShape(shape);
        layer.draw();
        saveHistory();
    }
}

// Add a shape button to the UI
function addShapeButtons() {
    const toolSection = document.querySelector('.tool-section:nth-child(3)');
    const shapeSection = document.createElement('div');
    shapeSection.className = 'tool-section';
    shapeSection.innerHTML = `
        <h3>Add Shape</h3>
        <div class="btn-group">
            <button id="addCircle" class="tool-btn">Circle</button>
            <button id="addRect" class="tool-btn">Rectangle</button>
            <button id="addTriangle" class="tool-btn">Triangle</button>
        </div>
    `;
    
    toolSection.parentNode.insertBefore(shapeSection, toolSection.nextSibling);
    
    // Add event listeners
    document.getElementById('addCircle').addEventListener('click', () => addNewShape('circle'));
    document.getElementById('addRect').addEventListener('click', () => addNewShape('rect'));
    document.getElementById('addTriangle').addEventListener('click', () => addNewShape('triangle'));
}

// Initialize editor
function initEditor() {
    // Set initial stage size (keeping it fixed size for round skin)
    const container = document.getElementById('editor');
    
    // Add shape buttons to the UI
    addShapeButtons();
    
    // Add default skin
    addDefaultSkin();
    
    // Check for autosaved content
    const savedData = localStorage.getItem('bonkverseSkinEditor');
    if (savedData) {
        try {
            layer.destroyChildren();
            document.getElementById('layerList').innerHTML = '';
            
            // Load saved skin data
            const newLayer = Konva.Node.create(savedData, 'editor');
            layer.draw();
            saveHistory();
        } catch (e) {
            console.log('Could not load autosaved content');
            // If loading fails, create a default skin
            addDefaultSkin();
        }
    }
    
    // Handle stage clicks for shape selection
    stage.on('click tap', function(e) {
        // Prevent selecting the background or stage itself
        if (e.target === stage || e.target.name() === 'skin-background') {
            return;
        }
        
        // Only select shapes, not transformers
        if (!e.target.hasName('transformer')) {
            const shape = e.target;
            selectShape(shape);
        }
    });
}

// Initialize the editor on load
window.addEventListener('load', initEditor);

// Resize handler
window.addEventListener('resize', function() {
    const container = document.getElementById('editor');
    stage.width(container.clientWidth);
    stage.height(container.clientHeight);
    layer.draw();
});
