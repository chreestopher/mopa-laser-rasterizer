# MOPA-LASER-RASTERIZER

Simple web form for processing image files to prepare for color engraving on stainless steel

## To use this app:
### Add your laser settings for each color to a LightBurn material settings file
Make sure the MaterilName contains "stainless steel"

Make sure the Material Settings Description matches one of the following descriptions:

| Description | hex color code for layer |
| --- | --- |
| Light-Gray  | #B4B4B4 |
| Black | #000000 |
| Blue | #0000FF |
| Red | #FF0000 | 
| Green | #00E000 |
| Yellow | #D0D000 |
| Orange | #FF8000 |
| Cyan | #00E0E0 |
| Magenta | #FF00FF |
| Dark-Blue | #0000A0 |
| Dark-Red | #A00000 |
| Dark-Green | #00A000 |
| Dark-Yellow | #A0A000 |
| Dark-Orange | #C08000 |
| Light-Blue | #00A0FF |
| Dark-Magenta | #A000A0 |
| Medium-Gray | #808080 |
| Slate-Blue | #7D87B9 |
| Rose | #BB7784 |
| Periwinkle-Blue | #4A6FE3 |
| Raspberry | #D33F6A |
| Sage-Green | #8CD78C |
| Peach | #F0B98D |
| Light-Pink | #F6C4E1 |
| Orchid-Pink | #FA9ED4 |
| Deep-Purple | #500A78 |
| Rust-Brown | #B45A00 |
| Teal | #004754 |
| Bright-Mint-Green | #86FA88 |
| Light-Gold | #FFDB66 |

## Project Structure

```
mopa-laser-rasterizer/
├── app.py               # Main server application
├── static/                   # Static HTML files directory
│   └── index.html          # Add your HTML files here
├── templates/              # Templated HTML files directory
├── lib/                    # Core library and utility modules
│   ├── lightburn.py        # library for interacting with LightBurn project and material files
│   └── Material_Library.py # process sent file with sent material settings file
└── README.md               # This file
```

## Getting Started

### Prerequisites

- Python 3.6 or higher
- pip install -r requirements.txt

### Running the Server 

1. Open a terminal in the project directory
2. Run the server:
   ```bash
   python app.py
   ```
3. Open your browser and navigate to: `http://localhost:8000`
