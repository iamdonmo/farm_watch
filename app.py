@app.post("/submit-registration")
def handle_registration(name: str = Form(...), phone: str = Form(...), zone: str = Form(...)):
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    db["farmers"][clean_phone] = {"name": name, "zone": zone}
    db_engine.save_db(db)
    
    print(f"\n💾 [WEB REGISTRATION] {name} added under {zone} with number: {clean_phone}")
    
    # 🌟 FIXED: Return a beautiful public success page instead of redirecting to the private dashboard!
    return HTMLResponse(content=f"""
    <html>
        <body style="font-family: sans-serif; background-color: #f4f7f6; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; padding: 20px;">
            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); width: 100%; max-width: 400px; text-align: center;">
                <h2 style="color: #27ae60; margin-top: 0;">✅ Registration Successful!</h2>
                <p style="color: #34495e; line-height: 1.5;">Thank you, <strong>{name}</strong>. Your device has been successfully linked to the <strong>{zone}</strong> Security Watch Network Grid.</p>
                <hr style="border: 0; border-top: 1px solid #cbd5e1; margin: 20px 0;">
                <a href="/" style="display: inline-block; background: #34495e; color: white; padding: 12px 20px; text-decoration: none; border-radius: 6px; font-weight: bold;">⬅️ Back to Homepage</a>
            </div>
        </body>
    </html>
    """) 
