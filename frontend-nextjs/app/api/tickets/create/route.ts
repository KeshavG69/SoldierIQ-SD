import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { subject, description, priority, email, name } = body;

    // Validate required fields
    if (!subject || !description || !email || !name) {
      return NextResponse.json(
        { error: 'Missing required fields' },
        { status: 400 }
      );
    }

    // Zendesk credentials from environment
    const subdomain = process.env.NEXT_PUBLIC_ZENDESK_SUBDOMAIN;
    const email_auth = process.env.ZENDESK_EMAIL;
    const api_token = process.env.ZENDESK_API_TOKEN;

    console.log('🔍 Zendesk Config Check:');
    console.log('  - Subdomain:', subdomain ? '✅ Set' : '❌ Missing');
    console.log('  - Email:', email_auth ? `✅ ${email_auth}` : '❌ Missing');
    console.log('  - API Token:', api_token ? `✅ ${api_token.substring(0, 10)}...` : '❌ Missing');

    if (!subdomain || !email_auth || !api_token) {
      console.error('❌ Zendesk credentials not configured properly');
      return NextResponse.json(
        { error: 'Support system not configured' },
        { status: 500 }
      );
    }

    // Create ticket via Zendesk API
    const zendeskUrl = `https://${subdomain}.zendesk.com/api/v2/tickets.json`;

    const ticketData = {
      ticket: {
        subject: subject,
        comment: {
          body: description,
        },
        priority: priority || 'normal',
        requester: {
          name: name,
          email: email,
        },
        tags: ['soldieriq', 'web-app'],
      },
    };

    const authString = `${email_auth}/token:${api_token}`;
    const authBase64 = Buffer.from(authString).toString('base64');

    console.log('🔑 Auth String Format:', `${email_auth}/token:${api_token.substring(0, 10)}...`);
    console.log('📍 Zendesk URL:', zendeskUrl);

    const response = await fetch(zendeskUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Basic ${authBase64}`,
      },
      body: JSON.stringify(ticketData),
    });

    if (!response.ok) {
      const errorData = await response.text();
      console.error('Zendesk API error:', errorData);
      return NextResponse.json(
        { error: 'Failed to create ticket' },
        { status: response.status }
      );
    }

    const data = await response.json();

    return NextResponse.json({
      success: true,
      ticket_id: data.ticket.id,
      message: 'Ticket created successfully',
    });
  } catch (error: any) {
    console.error('Ticket creation error:', error);
    return NextResponse.json(
      { error: error.message || 'Internal server error' },
      { status: 500 }
    );
  }
}
